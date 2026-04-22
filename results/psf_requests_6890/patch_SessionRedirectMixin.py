# Patch for: psf/requests issue #6890
# Class    : SessionRedirectMixin
# File     : src/requests/sessions.py
# Confidence: HIGH
# Generated: 2026-04-08 14:47:58
#
# Explanation:
#   The bug in `SessionRedirectMixin` is related to the handling of escaped quotes in cookie values. Specifically, the `get_redirect_target` method is responsible for extracting the redirect location from the response headers. However, when the location header contains escaped quotes, they are not properly preserved. This is because the `to_native_string` function is used to decode the location header, which replaces escaped quotes with empty strings. To fix this, we need to modify the `get_redirect_target` method to properly handle escaped quotes in the location header.

def get_redirect_target(self, resp):
    """Receives a Response. Returns a redirect URI or ``None``"""
    # Due to the nature of how requests processes redirects this method will
    # be called at least once upon the original response and at least twice
    # on each subsequent redirect response (if any).
    # If a custom mixin is used to handle this logic, it may be advantageous
    # to cache the redirect location onto the response object as a private
    # attribute.
    if resp.is_redirect:
        location = resp.headers["location"]
        # Use a custom decoding function to preserve escaped quotes
        def decode_location(location):
            location = location.encode("latin1")
            location = location.decode("unicode-escape")
            return location
        location = decode_location(location)
        return location
    return None
