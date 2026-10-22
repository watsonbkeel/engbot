const test=require('node:test'); const assert=require('node:assert/strict'); const fs=require('node:fs'); const os=require('node:os'); const path=require('node:path'); const {spawnSync}=require('node:child_process')
const root=path.resolve(__dirname,'..'), python=process.env.PYTHON||'python3'
function run(args){const result=spawnSync(python,[path.join(root,'scripts/make_listening.py'),...args],{cwd:root,encoding:'utf8',timeout:60000});assert.ifError(result.error);return result}
// macOS may expose /var or /tmp as aliases. Canonicalize only the trusted test
// temporary base; production continues to reject links in supplied asset paths.
function temporaryDirectory(prefix){return fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()),prefix))}
test('delivered listening assets pass independent manifest, digest, and ffprobe verification',()=>{
  const result=run(['--verify-only']); assert.equal(result.status,0,result.stderr||result.stdout)
  assert.match(result.stdout,/45/)
})
test('curated listening contains nine grades with five original texts and both types',()=>{
  const items=JSON.parse(fs.readFileSync(path.join(root,'data/listening/curated.json'))).items
  assert.equal(items.length,45); assert.equal(new Set(items.map(x=>x.id)).size,45)
  for(let grade=1;grade<=9;grade++){const rows=items.filter(x=>x.grade===grade);assert.equal(rows.length,5);for(const type of ['story','dialogue'])assert.ok(rows.filter(x=>x.type===type).length>=2)}
  for(const row of items){assert.ok(row.transcript.length>400);assert.match(row.file,new RegExp('^g'+row.grade+'/[A-Za-z0-9_-]+\\.mp3$'))}
})
test('generation rejects traversal in curated source before making any output',()=>{
  const tmp=temporaryDirectory('english-listening-')
  try{
    const src=JSON.parse(fs.readFileSync(path.join(root,'data/listening/curated.json')));src.items[0].file='../escape.mp3'
    const file=path.join(tmp,'curated.json');fs.writeFileSync(file,JSON.stringify(src));const output=path.join(tmp,'out')
    const result=run(['--source',file,'--output',output,'--limit','1'])
    assert.notEqual(result.status,0);assert.match(result.stderr,/\[ASSET_PATH_INVALID\]/);assert.equal(fs.existsSync(output),false)
  }finally{fs.rmSync(tmp,{recursive:true,force:true})}
})
test('verification never rewrites the delivered manifest or audio',()=>{
  const file=path.join(root,'data/listening/index.json'),before=fs.statSync(file)
  const result=run(['--verify-only']);assert.equal(result.status,0,result.stderr)
  assert.equal(fs.statSync(file).mtimeMs,before.mtimeMs)
})
test('missing real voice model produces a failure record without substitute audio',()=>{
  const tmp=temporaryDirectory('english-voice-fail-')
  try{
    const output=path.join(tmp,'assets'), result=run(['--backend','piper','--piper-model',path.join(tmp,'missing.onnx'),'--output',output,'--limit','1'])
    assert.equal(result.status,1,result.stderr||result.stdout);const failures=JSON.parse(fs.readFileSync(path.join(output,'failures.json')))
    assert.equal(failures.failed.length,1);assert.equal(failures.generated,0);assert.equal(failures.complete,false)
    assert.equal(failures.failed[0].code,'PIPER_MODEL_MISSING')
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(output,'index.json'))).items,[])
    assert.equal(fs.existsSync(path.join(output,'g1/g1_story_01.mp3')),false)
    assert.equal(fs.existsSync(path.join(output,'.build.lock')),false)
  }finally{fs.rmSync(tmp,{recursive:true,force:true})}
})
test('asset validation rejects tampered audio and atomic metadata preserves explicit permissions',()=>{
  const script=`import sys,json,tempfile,pathlib,shutil,stat
sys.path.insert(0,'scripts')
import make_listening as m
source=pathlib.Path('data/listening');entry=json.loads((source/'index.json').read_text())['items'][0]
original=json.loads((source/'curated.json').read_text())['items'][0]
with tempfile.TemporaryDirectory() as tmp:
 root=pathlib.Path(tmp).resolve();target=root/entry['file'];target.parent.mkdir();target.write_bytes(b'corrupt')
 try:m.validate_asset(entry,original,root)
 except m.BuildError as exc:assert exc.code=='ASSET_DIGEST_MISMATCH', str(exc)
 else:raise AssertionError('corrupted audio was accepted')
 metadata=root/'index.json';metadata.write_text('{}');metadata.chmod(0o640)
 m.atomic_json(metadata,{'items':[]});assert stat.S_IMODE(metadata.stat().st_mode)==0o640
`
  const result=spawnSync(python,['-c',script],{cwd:root,encoding:'utf8',timeout:30000});assert.ifError(result.error);assert.equal(result.status,0,result.stderr)
})
test('listening fixtures work with a symlinked system temporary directory',()=>{
  const tmp=temporaryDirectory('english-temp-alias-')
  try{
    const physical=path.join(tmp,'physical'),alias=path.join(tmp,'alias')
    fs.mkdirSync(physical);fs.symlinkSync(physical,alias,'dir')
    const env={...process.env,PYTHON:python,TMPDIR:alias,TEMP:alias,TMP:alias}
    // This is a new standalone runner, not a child in the parent's test IPC context.
    delete env.NODE_TEST_CONTEXT
    const result=spawnSync(process.execPath,[
      '--test-reporter=tap',
      '--test-name-pattern=missing real voice model|asset validation rejects tampered audio',
      __filename
    ],{cwd:root,env,encoding:'utf8',timeout:30000})
    assert.ifError(result.error)
    assert.equal(result.status,0,result.stderr||result.stdout)
    assert.match(result.stdout,/# pass 2\b/)
  }finally{fs.rmSync(tmp,{recursive:true,force:true})}
})
