"""Shared current model-call concurrency and strict JSON decoding."""

from threading import BoundedSemaphore

_MODEL_SLOTS = BoundedSemaphore(3)


def global_model_slots():
    return _MODEL_SLOTS


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value
