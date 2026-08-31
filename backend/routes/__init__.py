"""HTTP layer — thin FastAPI routers, one per feature surface.

Parse/validate the request, call into agent/services, shape the response, apply
the auth gate. No business logic in a handler.
"""
