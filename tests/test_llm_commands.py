import json
import threading
import time
import unittest
from unittest.mock import patch
from agentic_uav.comm.llm_commands import CommandReceiver, LLMCommandWorker, validate_target


class CommandTests(unittest.TestCase):
    def test_schema_rejects_invalid_and_nonfinite(self):
        self.assertEqual(validate_target({'target':[1,2,25]}),(1.,2.,25.))
        for payload in ({'target':[1,2]}, {'target':[True,2,25]}, {'target':[1,2,float('nan')]},
                        {'target':[1,2,25],'land':True}):
            with self.assertRaises(ValueError): validate_target(payload)

    def test_expiry_drop_order_and_latch(self):
        r=CommandReceiver();c=dict(sequence=1,expires_at=5)
        self.assertEqual(r.receive(c,1,False),'dropped')
        self.assertEqual(r.receive(c,5,True),'expired')
        self.assertEqual(r.receive(c,1,True),'accepted')
        self.assertEqual(r.receive(c,2,True),'duplicate_or_out_of_order')
        r.latched=True
        self.assertEqual(r.receive(dict(sequence=2,expires_at=10),3,True),'suppressed_after_timeout')

    def test_slow_generation_never_blocks_poll(self):
        started,release=threading.Event(),threading.Event()
        def generate(worker,state):
            started.set();release.wait(2)
            return json.dumps({'target':[1,2,25]})
        with patch.object(LLMCommandWorker,'_generate',generate):
            w=LLMCommandWorker('ollama','test',1,20,'test')
            try:
                w.submit(1,{})
                self.assertTrue(started.wait(1))
                self.assertIsNone(w.poll())  # Request is demonstrably still blocked in the worker.
                release.set()
                deadline=time.monotonic()+1
                result=None
                while result is None and time.monotonic()<deadline:
                    result=w.poll();time.sleep(.001)
                self.assertEqual(result['target'],(1.,2.,25.))
            finally:
                release.set();w.close()
