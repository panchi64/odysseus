"""Claim-level attribution for one assistant turn — what the answer asserted, and
which source (if any) each assertion actually rests on.

A citation on a message says *that* a page was read. It does not say which sentence in
it carried which claim, which is the thing an operator opens a citation to check — and
the failure they report is never "no citation", it is a citation that, when opened, did
not say what was claimed. The triples stored here are the answer to that: they come from
a second reader that runs after the answer, over the answer, and a claim it could not
ground is a row like any other rather than an error.

**Keyed by the assistant turn's branch node**, the same id every operator surface already
addresses a turn by (`conversation_view.MessageView.id`). A regenerate is a different
node and therefore a different row, which is right — it is a different answer, and an
attribution carried across it would describe prose nobody wrote.

**One row per turn, not one per claim.** The whole set is extracted together, read
together and replaced together, it is small, and it is sealed as a unit — a row per claim
would buy nothing and cost a join plus per-row sealing. The claims are a sealed JSON
array: a claim is a verbatim span of the answer and a passage is a verbatim span of a
source the operator read, which is content rather than policy.

**Not to be confused with `models/conversation.py`'s messages**, which hold the answer
itself. This is a derived reading of one of them, and it is deliberately additive: a
thread with no row here renders exactly as it did before the pass existed.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from models._fields import new_id, utcnow


class MessageAttribution(SQLModel, table=True):
    __tablename__ = "message_attributions"

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    conversation_id: str = Field(index=True)
    # Unique: one assistant turn has one extraction, and the store upserts against it.
    # The branch node id, so the frontend can join these to the turns it already renders
    # without a second identity to keep in step.
    message_id: str = Field(index=True, unique=True)
    # AEAD ciphertext of the JSON array of claims (claim, source_key, source_title,
    # source_url, source_kind, passage, confidence, grounded, offset).
    claims_enc: str
    # When the pass ran. In the clear — it is a fact about the chassis, not about the
    # operator's content, and the retroactive path needs to be able to say how old a
    # reading is without unsealing it.
    extracted_at: datetime = Field(default_factory=utcnow, index=True)
