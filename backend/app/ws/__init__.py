"""WebSocket endpoints.

Two separate channels, on purpose:

* ``/ws/predict/{code}``  — landmarks in, recognised text out
* ``/ws/signal/{code}``   — WebRTC offer/answer/ICE relay (Phase 6)

They are kept apart because they have different lifetimes and different failure
modes. Multiplexing them onto one socket would mean a dropped video call also
kills sign recognition, which is precisely backwards: the recognition is the
part a deaf user cannot do without.
"""
