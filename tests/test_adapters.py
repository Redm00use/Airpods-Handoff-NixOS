import os
os.environ['AIRPODS_DEVICE']='AA:BB:CC:DD:EE:FF'
import unittest
from airpods_handoff import Adapter

class Streams(unittest.TestCase):
    def setUp(self):
        self.a=Adapter(True);self.a.identities={'cider':(10,'cider'),'chrome':(20,'chrome')}
    def node(self,name,role=None,state='running',mute=False):
        return {'info':{'state':state,'props':{'media.class':'Stream/Output/Audio','application.name':name,'media.role':role},'params':{'Props':[{'mute':mute}]}}}
    def test_cider_alsa_identity(self):
        self.a.nodes={1:self.node('PipeWire ALSA [Cider]')};self.a.correlate();self.assertEqual(self.a.policy.streams,{'cider'})
    def test_notifications_and_virtual_nodes_excluded(self):
        self.a.nodes={1:self.node('Cider','Notification'),2:self.node('Noctalia'),3:self.node('EasyEffects')}
        self.a.correlate();self.assertEqual(self.a.policy.streams,set())
    def test_muted_or_idle_not_media(self):
        self.a.nodes={1:self.node('Cider',mute=True),2:self.node('Google Chrome',state='idle')}
        self.a.correlate();self.assertEqual(self.a.policy.streams,set())
    def test_non_live_prerecorded_music_is_eligible(self):
        node=self.node('Cider');node['info']['props']['stream.is-live']=False
        self.a.nodes={1:node};self.a.correlate();self.assertEqual(self.a.policy.streams,{'cider'})
    def test_browser_family(self):
        # MPRIS calls Chrome "chromium" while PipeWire uses "Google Chrome".
        self.a.identities['chrome']=(20,'chrome')
        self.a.nodes={1:self.node('Google Chrome')};self.a.correlate()
        self.assertEqual(self.a.policy.streams,{'chrome'})

if __name__=='__main__':unittest.main()
