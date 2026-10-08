<!-- Read by the triage of review-pr: when to ask the user about a finding. -->

# The review decision gate

Human attention is the scarce resource in a review, not analysis. A question is
worth asking only when the answer can change what gets published or committed
**and** the human is the only one who can give it. Everything else is presented,
not asked about.

**Doubt, or a decision about what the feature does, is what buys an item its own
question.** An item you could not settle against the code needs the person who
can settle it, and an item that changes the feature's behavior needs the person
who owns its intent. Every other item gets no question, whatever its severity and
whatever it blocks: it is shown in full, and the last call before publishing
covers the consequence for the whole set at once.

## Is the support mechanical, or is it judgment? (this is the only `ASK` test)

The support is **mechanical** when all four hold:

1. The offending line is quoted from the pinned head commit and shows what the
   finding claims.
2. The fix is a concrete change of a few lines, not a direction to explore.
3. A precedent (a `path:line` in this repo that already does it correctly) or a
   written rule (an `AGENTS.md` line, an ADR, a lint or type error, a failing
   test) supports it.
4. It is not a product, UX, or design tradeoff, and does not depend on intent
   only the author knows.

The support is **judgment** in every other case, including any finding whose
backing is "this reads better" or "I would have written it differently".

**The four tests decide, never the feeling.** "I am sure about this one" cannot
stand in for a test that failed, and "I want to be careful" cannot manufacture a
failure that did not happen. Both directions are the same error: reading your own
comfort instead of the evidence. Work the four tests item by item and take the
answer they give.
