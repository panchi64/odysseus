"""The scripted model behind a dev instance.

An OpenAI-compatible server that answers deterministically, can be told what to say, can
be made to fail, and can be made to take its time. It plugs into the registry through the
ordinary ``openai-compatible`` provider with no key, exactly as a local engine would.

:mod:`devkit.stub.app` is the server, :mod:`devkit.stub.scripts` is how it is told what
to say, and :mod:`devkit.stub.wire` is the format it says it in.
"""

from devkit.stub.app import MODEL_ID, create_stub

__all__ = ["MODEL_ID", "create_stub"]
