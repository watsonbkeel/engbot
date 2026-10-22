"""Optional nonblocking SSH power check. Configuration is server-owned only."""
from __future__ import annotations
import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path

LOG=logging.getLogger('english-class.status')

async def probe_ssh(host:str,runner=None) -> bool:
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@:\-]{0,200}',host):
        LOG.warning('PI_SSH_HOST must be a host alias or user@host, without command options')
        return False
    argv=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5','-o','StrictHostKeyChecking=accept-new',
          '-o','UserKnownHostsFile='+os.environ.get('PI_SSH_KNOWN_HOSTS','/var/lib/english-class/pi_known_hosts')]
    config=os.environ.get('PI_SSH_CONFIG','/etc/english-class/pi_ssh_config')
    if Path(config).is_file(): argv.extend(['-F',config])
    key=os.environ.get('PI_SSH_KEY','/etc/english-class/pi_ssh_key')
    if key: argv.extend(['-i',key])
    argv.extend([host,'true'])
    process=None
    try:
        if runner is not None:
            async with asyncio.timeout(7): return await runner(argv)==0
        process=await asyncio.create_subprocess_exec(*argv,stdin=asyncio.subprocess.DEVNULL,
                                                   stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
        async with asyncio.timeout(7): return await process.wait()==0
    except (TimeoutError,OSError): return False
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()

async def probe_once(store,host,runner=None):
    students=store.student_ids()
    if isinstance(host,str):
        if len(students)!=1:
            LOG.warning('Multiple students require explicit PI_SSH_HOSTS mapping; no ambiguous power status recorded')
            return
        hosts={students[0]:host}
    else: hosts=host
    slots=asyncio.Semaphore(4)
    async def one(student_id):
        device=hosts.get(student_id)
        if not device: return
        state=store.status(student_id)
        try:
            age=(datetime.fromisoformat(state['server_time'])-datetime.fromisoformat(state['pi_last_seen'])).total_seconds()
        except (TypeError,ValueError): age=float('inf')
        if 0<=age<=30: return
        async with slots:
            store.mark_pi_ssh(student_id,await probe_ssh(device,runner))
    await asyncio.gather(*(one(student_id) for student_id in students))

async def probe_loop(store,host):
    while True:
        try: await probe_once(store,host)
        except Exception: LOG.exception('Optional Pi status probe failed')
        await asyncio.sleep(30)
