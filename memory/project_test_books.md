---
name: Test Books
description: Context on the two real test books used for development
type: project
---

**A Parade of Horribles** is the primary test book. Clean EPUB, 115 chapters, LitRPG genre (large cast, ~256 speaking characters). 99.8% attribution accuracy after LLM pass. Use this for feature validation.

**Why:** Best representative of a real, well-structured EPUB.

**How to apply:** When evaluating pipeline changes, use Parade numbers. The 256-character list is expected and correct.

---

**Carousel B8 Ch17-30** is a stress test only, not representative. Source is copy-pasted web chapters reformatted as EPUB with minimal structure by the user. Mostly first-person POV (narrator = protagonist, so most dialogue is self-narration). Occasional interlude chapters switch POV. Incomplete book (8 chapters, not full).

**Why:** High unresolved count (103) is expected given the format, not a pipeline failure. The user manually created this EPUB.

**How to apply:** Don't use Carousel stats to judge attribution quality. Use it only for stress-testing edge cases like POV switches and minimal EPUB structure.
