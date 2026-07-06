import os, sys, unittest
sys.path.insert(0, os.path.dirname(__file__))
from _capability import loopback_available

class TestCapability(unittest.TestCase):
    def test_returns_bool(self):
        self.assertIn(loopback_available(), (True, False))

    def test_matches_actual_bind(self):
        import os
        if os.environ.get("CSSWITCH_FORCE_NO_LOOPBACK") == "1":
            # FORCE 模拟下探针本就应该强制返回 False，与真实 bind 是否可行无关。
            self.assertFalse(loopback_available())
            return
        import socket
        try:
            s = socket.socket(); s.bind(("127.0.0.1", 0)); s.close()
            can = True
        except OSError:
            can = False
        self.assertEqual(loopback_available(), can)

    def test_force_no_loopback_env(self):
        import os
        name = "CSSWITCH_FORCE_NO_LOOPBACK"
        prev = os.environ.get(name)
        os.environ[name] = "1"
        try:
            self.assertFalse(loopback_available())
        finally:
            if prev is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = prev

if __name__ == "__main__":
    unittest.main()
