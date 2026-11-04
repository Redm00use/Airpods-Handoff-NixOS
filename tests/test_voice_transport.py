import unittest
from airpods_voice_transport import VoiceTransport,VoiceProcess
from airpods_call_detection import CallTracker

class VoiceLiveness(unittest.TestCase):
    def setUp(self):
        self.snapshot=VoiceProcess('started',frozenset({'10'}));self.probes=[]
        def probe(pid):self.probes.append(pid);return self.snapshot
        self.monitor=VoiceTransport(probe);self.tracker=CallTracker(voice_transport=self.monitor)
    def graph(self,streams=True,binary='.DiscordCanary-wrapped',serial=91):
        result={}
        for i in (1,2):result[i]={'type':'PipeWire:Interface:Client','info':{'props':{
            'application.name':'WEBRTC VoiceEngine','application.process.binary':binary,
            'application.process.id':42,'object.serial':serial+i}}}
        if streams:
            for i,kind in ((1,'Input'),(2,'Output')):
                result[i+10]={'type':'PipeWire:Interface:Node','info':{'state':'running','props':{
                    'media.class':'Stream/'+kind+'/Audio','client.id':i}}}
        return result
    def establish(self,binary='.DiscordCanary-wrapped'):
        self.tracker.observe(0,self.graph(binary=binary))
        self.assertTrue(self.tracker.observe(.21,self.graph(binary=binary)))
        self.tracker.observe(2.1,self.graph(binary=binary))
    def test_proven_native_discord_survives_absent_audio_nodes(self):
        self.establish()
        self.assertTrue(self.tracker.observe(3,self.graph(False)))
        self.assertTrue(self.tracker.observe(30,self.graph(False)))
        self.assertEqual(self.tracker.evidence,('discord',))
        self.assertEqual(self.tracker.deadline(30),32)
    def test_hangup_closes_voice_socket_even_when_voice_clients_remain(self):
        self.establish();self.tracker.observe(3,self.graph(False))
        self.snapshot=VoiceProcess('started',frozenset())
        self.assertTrue(self.tracker.observe(4.2,self.graph(False)))
        self.assertFalse(self.tracker.observe(5.46,self.graph(False)))
        self.assertFalse(self.monitor.records)
    def test_client_or_pid_reuse_does_not_inherit_call(self):
        for change in ('client','process'):
            self.setUp();self.establish()
            if change=='process':self.snapshot=VoiceProcess('restarted',frozenset({'10'}))
            graph=self.graph(False,serial=100 if change=='client' else 91)
            self.tracker.observe(4.2,graph)
            self.assertFalse(self.tracker.observe(5.46,graph))
    def test_different_udp_socket_cannot_replace_proven_voice_connection(self):
        self.establish();self.snapshot=VoiceProcess('started',frozenset({'20'}))
        self.tracker.observe(4.2,self.graph(False))
        self.assertFalse(self.tracker.observe(5.46,self.graph(False)))
    def test_voice_clients_or_udp_alone_never_start_a_call(self):
        for now in (0,1,3,100):self.assertFalse(self.tracker.observe(now,self.graph(False)))
        self.assertFalse(self.probes)
    def test_browser_duplex_does_not_get_native_discord_retention(self):
        self.establish('zen')
        self.tracker.observe(3,self.graph(False,binary='zen'))
        self.assertFalse(self.tracker.observe(4.26,self.graph(False,binary='zen')))
        self.assertFalse(self.probes)
    def test_kernel_probe_failure_releases_instead_of_guessing(self):
        self.establish();self.snapshot=None
        self.tracker.observe(4.2,self.graph(False))
        self.assertFalse(self.tracker.observe(5.46,self.graph(False)))
