"""Exact Chinese posture commands over the existing robotd JSON-RPC contract."""
import json
import math
import re
import socket
import time
import os
from pathlib import Path
from contextlib import contextmanager

UPDATE_MARKER=Path('/run/microduck-updater/installing')

class UpdateLocked(RuntimeError): pass

def updates_allowed(): return not UPDATE_MARKER.exists()

@contextmanager
def motion_lease(marker=UPDATE_MARKER,lock=None):
    """Finish existing actions before root's EX preflight; reject new actions."""
    marker=Path(marker);lock=Path(lock) if lock else marker.parent/'motion.lock'
    if marker.exists():raise UpdateLocked('software update in progress')
    descriptor=None
    try:
        try:descriptor=os.open(lock,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        except FileNotFoundError:
            # Legacy installation without the updater has no update lease yet.
            if marker.exists():raise UpdateLocked('software update in progress')
        if descriptor is not None:
            import fcntl
            try:fcntl.flock(descriptor,fcntl.LOCK_SH|fcntl.LOCK_NB)
            except BlockingIOError:raise UpdateLocked('software update in progress') from None
        if marker.exists():raise UpdateLocked('software update in progress')
        yield
    finally:
        if descriptor is not None:os.close(descriptor)


def parse_command(text, confidence):
    if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or confidence < 0.75:
        return None
    text = re.sub(r'[\s，。！？、,.!?]', '', text)
    for address in ('小鸭子', '鸭子'):
        if text.startswith(address):
            text = text[len(address):]
            break
    if text.startswith('请'):
        text = text[1:]
    for suffix in ('一下', '吧'):
        if text.endswith(suffix):
            text = text[:-len(suffix)]
            break
    if text in ('坐下', '坐下来'):
        return 'sit'
    if text in ('站起来', '站起', '起立', '起来'):
        return 'stand'
    return None


class RobotClient:
    def __init__(self, path='/run/robotd.sock', timeout=1.5):
        self.path, self.timeout = path, timeout

    def call(self, method, params=None):
        request = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(self.timeout)
            client.connect(self.path)
            client.sendall((json.dumps(request) + '\n').encode())
            with client.makefile('rb') as stream:
                response = stream.readline(1024 * 1024 + 1)
            if not response or len(response) > 1024 * 1024:
                raise RuntimeError('invalid or oversized robotd response')
            result = json.loads(response)
            if result.get('id') != 1 or 'error' in result:
                raise RuntimeError('robotd refused ' + method + ': ' + str(result.get('error')))
            data = result.get('result')
            if not isinstance(data, dict):
                raise RuntimeError('robotd returned an unexpected result for ' + method)
            return data


class PostureCommands:
    def __init__(self, robot, timeout=4, sleep=time.sleep,guard=updates_allowed,lease=motion_lease):
        self.robot, self.timeout, self.sleep = robot, timeout, sleep
        self.guard,self.lease=guard,lease

    def state(self):
        policies = self.robot.call('robot.policies')
        bus = self.robot.call('robot.busStatus')
        if not isinstance(policies.get('sitting'), bool):
            raise RuntimeError('cannot read current sitting state')
        if bus.get('phase') != 'control' or bus.get('mode') != 'motion':
            raise RuntimeError('robot is not in motion control mode')
        return policies, bus

    def execute(self, command, allowed=lambda: True):
        try:
            if not self.guard():raise UpdateLocked('software update in progress')
            with self.lease():
                return self._execute(command,lambda:allowed() and self.guard())
        except UpdateLocked as error:return {'accepted':False,'reason':str(error)}

    def _execute(self,command,allowed):
        if command not in ('sit', 'stand'):
            return {'accepted': False, 'reason': 'unknown command'}
        try:
            policies, bus = self.state()
            if not allowed():
                return {'accepted': False, 'reason': 'cancelled'}
            desired = command == 'sit'
            torque = bus.get('native', {}).get('torque_state_confirmed') is True
            homed = policies.get('homed') is True or bus.get('homed') is True
            initialized = False

            def request(method, params=None):
                if not allowed():
                    raise RuntimeError('cancelled')
                result = self.robot.call(method, params)
                if result.get('accepted') is not True:
                    raise RuntimeError(str(result.get('reason', method + ' was refused')))

            if policies['sitting'] == desired and (desired or (torque and homed)):
                return {'accepted': True, 'changed': False, 'sitting': desired}
            if command == 'stand' and not policies['sitting'] and not torque:
                request('robot.init')
                initialized = True
            else:
                if not torque or not homed:
                    raise RuntimeError('robot must be upright and homed with torque confirmed')
                if not any(isinstance(slot, dict) and slot.get('slot') == 'sitstand'
                           and slot.get('path') and not slot.get('error')
                           for slot in policies.get('slots', [])):
                    raise RuntimeError('sit/stand policy is not installed')
                if bus.get('policy_enabled') is not True:
                    if policies['sitting']:
                        raise RuntimeError('sitting with policy off; use the existing recovery procedure')
                    request('robot.stop')
                    request('robot.enable', {'on': True, 'toggle': False})
                    deadline = time.monotonic() + 1.2
                    while True:
                        _, bus = self.state()
                        if bus.get('policy_enabled') is True:
                            break
                        if time.monotonic() >= deadline or not allowed():
                            raise RuntimeError('policy enable was not confirmed')
                        self.sleep(0.05)
                # Refresh the toggle state immediately before using the toggle API.
                policies, _ = self.state()
                if policies['sitting'] != desired:
                    request('robot.do', {'skill': 'sit_toggle'})
            deadline = time.monotonic() + self.timeout
            while allowed():
                policies, bus = self.state()
                ready = policies['sitting'] == desired
                if initialized:
                    ready = ready and (policies.get('homed') is True or bus.get('homed') is True)
                    ready = ready and bus.get('native', {}).get('torque_state_confirmed') is True
                if ready:
                    return {'accepted': True, 'changed': True, 'sitting': desired}
                if time.monotonic() >= deadline:
                    raise RuntimeError('posture request accepted but target state not confirmed')
                self.sleep(0.08)
            return {'accepted': False, 'reason': 'cancelled'}
        except (OSError, ValueError, RuntimeError) as error:
            return {'accepted': False, 'reason': str(error)}
