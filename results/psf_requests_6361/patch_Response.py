# Patch for: psf/requests issue #6361
# Class    : Response
# File     : src/requests/models.py
# Confidence: HIGH
# Generated: 2026-04-08 14:40:16
#
# Explanation:
#   The bug in the `Response` class is that the `_next` attribute is not being pickled when the object is serialized. This is because the `__getstate__` method only includes attributes listed in `__attrs__`, and `_next` is not in this list. To fix this, we need to modify the `__getstate__` method to include the `_next` attribute. We can do this by adding `_next` to the dictionary returned by `__getstate__`. This will ensure that the `_next` attribute is properly pickled and can be restored when the object is deserialized.

def __getstate__(self):
    # Consume everything; accessing the content attribute makes
    # sure the content has been fully read.
    if not self._content_consumed:
        self.content

    state = {attr: getattr(self, attr, None) for attr in self.__attrs__}
    state['_next'] = self._next  # Add _next to the state dictionary
    return state
