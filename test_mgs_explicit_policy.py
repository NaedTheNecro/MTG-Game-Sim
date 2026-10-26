import unittest
from mgs_explicit_policy import propose_decision, IntegrityAbort

class ExplicitPolicyTests(unittest.TestCase):
    def state(self, action_type, choices=None, seq=5):
        return {"action_pending":True,"game_seq":seq,"action_type":action_type,"choices":[] if choices is None else choices}
    def test_land_is_explicit(self):
        result=propose_decision(self.state("GAME_SELECT",[{"index":0,"action":"cast"},{"index":1,"action":"land"}]),seat=2)
        self.assertEqual(result.arguments,{"choice":"1","auto_tap":False})
        self.assertEqual(result.game_seq,5)
    def test_pass_is_explicit(self):
        self.assertEqual(propose_decision(self.state("GAME_SELECT"),seat=0).arguments["choice"],"no")
    def test_mulligan_declined_explicitly(self):
        self.assertEqual(propose_decision(self.state("GAME_ASK"),seat=1).arguments["choice"],"no")
    def test_target_by_engine_index(self):
        self.assertEqual(propose_decision(self.state("GAME_TARGET",[{"index":3}]),seat=3).arguments["choice"],"3")
    def test_mana_never_auto_taps(self):
        self.assertEqual(propose_decision(self.state("GAME_PLAY_MANA"),seat=0).arguments,{"choice":"no","auto_tap":False})
    def test_invalid_seat_rejected(self):
        with self.assertRaises(IntegrityAbort):propose_decision(self.state("GAME_ASK"),seat=4)
    def test_no_pending_decision_rejected(self):
        s=self.state("GAME_ASK");s["action_pending"]=False
        with self.assertRaises(IntegrityAbort):propose_decision(s,seat=0)
    def test_missing_seq_rejected(self):
        s=self.state("GAME_ASK");s.pop("game_seq")
        with self.assertRaises(IntegrityAbort):propose_decision(s,seat=0)
    def test_unknown_prompt_is_fatal(self):
        with self.assertRaises(IntegrityAbort):propose_decision(self.state("GAME_DECLARE_ATTACKERS"),seat=0)
    def test_no_target_not_auto_selected(self):
        with self.assertRaises(IntegrityAbort):propose_decision(self.state("GAME_TARGET"),seat=0)
    def test_malformed_choice_index_is_fatal(self):
        with self.assertRaises(IntegrityAbort):propose_decision(self.state("GAME_TARGET",[{"name":"x"}]),seat=0)
if __name__=="__main__":unittest.main()
