import sys
import os
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detection_state import DetectionState, state


def test_detection_state_instantiation():
    s = DetectionState()
    assert isinstance(s, DetectionState)


def test_state_singleton_type():
    assert isinstance(state, DetectionState)


def test_current_frame_lock_is_lock():
    s = DetectionState()
    assert isinstance(s.current_frame_lock, type(threading.Lock()))


def test_current_recording_lock_is_rlock():
    s = DetectionState()
    assert isinstance(s.current_recording_lock, type(threading.RLock()))


def test_current_pending_mask_lock_is_lock():
    s = DetectionState()
    assert isinstance(s.current_pending_mask_lock, type(threading.Lock()))
