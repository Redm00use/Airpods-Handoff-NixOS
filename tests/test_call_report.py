import asyncio
import unittest
from unittest.mock import AsyncMock
from airpods_handoff import Adapter

class Reports(unittest.IsolatedAsyncioTestCase):
    def setup_adapter(self):
        a=Adapter(False);p=a.policy;p.generation=1;p.connected=True;p.ready=True;p.local_call=True;p.call_proven=True
        a._cli=AsyncMock(return_value=(True,''));return a
    async def test_start_and_withdraw_once(self):
        a=self.setup_adapter();a.sync_call_report();await a.call_report_task
        a.sync_call_report();self.assertEqual(a._cli.await_count,1)
        a.policy.local_call=False;a.policy.call_proven=False;a.sync_call_report();await a.call_report_task
        self.assertEqual([c.args for c in a._cli.await_args_list],[('switching','call-start'),('switching','call-end')])
        a.sync_call_report();self.assertEqual(a._cli.await_count,2)
    async def test_fresh_call_without_local_proof_never_announced(self):
        a=self.setup_adapter();a.policy.call_proven=False;a.sync_call_report()
        self.assertIsNone(a.call_report_task);a._cli.assert_not_awaited()
    async def test_session_change_reannounces(self):
        a=self.setup_adapter();a.sync_call_report();await a.call_report_task
        a.policy.generation+=1;a.sync_call_report();await a.call_report_task
        self.assertEqual(a._cli.await_count,2)
    async def test_hangup_while_waiting_for_ipc_never_sends_stale_start(self):
        a=self.setup_adapter();await a.ipc_lock.acquire();a.sync_call_report();await asyncio.sleep(0)
        a.policy.local_call=False;a.policy.call_proven=False;a.sync_call_report();a.ipc_lock.release()
        await asyncio.sleep(0);await asyncio.sleep(0);a._cli.assert_not_awaited()

    async def test_hangup_with_lost_start_ack_still_withdraws(self):
        a=self.setup_adapter();started=asyncio.Event()
        async def cli(*args):
            if args[-1]=='call-start':
                started.set();await asyncio.Future()
            return True,''
        a._cli.side_effect=cli;a.sync_call_report();await started.wait()
        a.policy.local_call=False;a.policy.call_proven=False;a.sync_call_report();await a.call_report_task
        self.assertEqual([c.args[-1] for c in a._cli.await_args_list],['call-start','call-end'])
        self.assertFalse(a.call_report_sent)
