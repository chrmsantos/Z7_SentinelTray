from unittest.mock import MagicMock

parent = MagicMock()
print("parent:", parent)
print("parent.after:", parent.after)
print("parent.after._mock_call:", parent.after._mock_call)
parent.after(0, lambda: print("called"))
print("Done")
