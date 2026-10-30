"""Offline sample course so the UI can be explored (and tested) with no API keys.

Seeds one topic whose files follow exactly the same schema the live pipeline
writes: a roadmap, a generated overview lesson with a diagram and source
references, a quiz, and a user-style source document for the split view.
"""

from __future__ import annotations

from . import schema, sources, workspace

SOURCE_NAME = "git_internals_notes.md"

SOURCE_TEXT = """# Git internals — my study notes

## Objects
Git is a content-addressable filesystem with a version-control interface on top.
Everything lives in the .git/objects directory as one of four object types: blob,
tree, commit and tag. Each object is named by the SHA-1 hash of its content.

A blob stores the raw bytes of one file. It has no filename and no permissions,
only content. Two files with identical content share a single blob.

A tree maps names to objects. It records filenames, modes, and the hash of either a
blob (a file) or another tree (a sub-directory). A tree is a snapshot of one folder.

A commit points to exactly one top-level tree, to zero or more parent commits, and
carries the author, committer, timestamp and message.

## The three areas
Your working directory holds the files you edit. The staging area, also called the
index, is a file at .git/index that lists exactly what the next commit will contain.
The repository is the .git directory holding every object ever stored.

Running git add hashes the file, writes a blob, and updates the index. Running git
commit turns the index into a tree, wraps it in a commit object, and moves the
current branch to point at that new commit.

## References
A branch is not a copy of your code. It is a tiny text file in .git/refs/heads
containing the 40-character hash of one commit. Creating a branch costs almost nothing.

HEAD is a file that normally contains a symbolic reference such as
ref: refs/heads/main, meaning "the branch I am currently on". When HEAD holds a raw
commit hash instead, you are in a detached HEAD state.

## Why it is safe
Because objects are immutable and named by their content, history cannot be edited in
place. Operations like amend or rebase create new commits and move references; the old
commits remain until garbage collection removes unreachable objects.
"""

LESSON_MD = """# Git Is a Photo Album, Not a Diff Machine

<!-- source-ref: {"file": "src_1", "page": 1, "quote": "content-addressable filesystem with a version-control interface"} -->
## The big idea

Most people picture Git as a tool that tracks *changes*. Under the hood it does something simpler and more powerful: it stores **snapshots** of your project, and it names every snapshot by a fingerprint of its content. Think of a photo album where each photo's label is computed from the picture itself. Same picture, same label, stored once.

That fingerprint is a **SHA-1 hash**, and everything Git keeps — files, folders, commits — is stored as an *object* named by its hash.

{{diagram: diagrams/lesson_1_fig1.mmd}}

<!-- source-ref: {"file": "src_1", "page": 1, "quote": "A blob stores the raw bytes of one file"} -->
## The three building blocks

- A **blob** is the raw content of one file. It has no name, only bytes — so two identical files share a single blob.
- A **tree** is a folder snapshot: a list of names pointing at blobs or other trees.
- A **commit** points at one top-level tree, plus its parent commit(s), author and message.

Follow the arrows from a commit and you can rebuild your whole project exactly as it was.

<!-- source-ref: {"file": "src_1", "page": 2, "quote": "git add hashes the file, writes a blob, and updates the index"} -->
## Three places your work lives

| Place | What it is | Moved by |
| :-- | :-- | :-- |
| Working directory | the files you edit | you |
| Staging area (index) | exactly what the next commit will contain | `git add` |
| Repository (`.git`) | every object ever stored | `git commit` |

The staging area is the surprise for newcomers. It lets you build a commit deliberately, picking only the changes that belong together.

<!-- source-ref: {"file": "src_1", "page": 2, "quote": "A branch is not a copy of your code"} -->
## Branches are just sticky notes

A branch is a tiny file holding the hash of one commit. Creating one costs almost nothing, which is why Git users branch freely. **HEAD** is a note that says *which branch you are on*.

> If a branch is only a pointer, then "merging" and "rebasing" are really about moving pointers and creating new commits — never about editing old ones.

## Key takeaways

- Git stores **snapshots**, named by the hash of their content.
- Blob = file content, tree = folder, commit = snapshot plus history.
- `git add` fills the index; `git commit` turns the index into a commit.
- A branch is a pointer to a commit, and HEAD points at the current branch.
"""

DIAGRAM = """flowchart LR
    C[Commit] --> T[Tree: project root]
    C -. parent .-> P[Previous commit]
    T --> B1[Blob: main.py]
    T --> T2[Tree: docs]
    T2 --> B2[Blob: guide.md]
    BR[Branch main] --> C
    H[HEAD] --> BR"""

QUIZ = {"questions": [
    {"id": "q1", "prompt": "What is a Git blob?", "options": [
        {"id": "a", "text": "The raw content of a single file, with no filename"},
        {"id": "b", "text": "A snapshot of an entire folder"},
        {"id": "c", "text": "A pointer to the current branch"},
        {"id": "d", "text": "A compressed list of commits"}], "correct_option_id": "a",
     "explanation": "Blobs hold only bytes. Filenames live in trees, which point at blobs.",
     "concept_tag": "objects"},
    {"id": "q2", "prompt": "Two files in different folders have identical content. How many blobs does Git store?", "options": [
        {"id": "a", "text": "Two, one per file path"},
        {"id": "b", "text": "One, because objects are named by content hash"},
        {"id": "c", "text": "Zero until the first commit"},
        {"id": "d", "text": "Three, including a tree"}], "correct_option_id": "b",
     "explanation": "Same content produces the same hash, so the object is stored once and shared.",
     "concept_tag": "objects"},
    {"id": "q3", "prompt": "What does git commit do with the staging area?", "options": [
        {"id": "a", "text": "Deletes it"},
        {"id": "b", "text": "Copies the working directory into it"},
        {"id": "c", "text": "Turns it into a tree wrapped by a new commit, then moves the branch"},
        {"id": "d", "text": "Uploads it to a remote"}], "correct_option_id": "c",
     "explanation": "The index becomes a tree, the commit references it, and the current branch pointer advances.",
     "concept_tag": "staging"},
    {"id": "q4", "prompt": "What is a branch, physically?", "options": [
        {"id": "a", "text": "A full copy of the project"},
        {"id": "b", "text": "A folder under .git/branches"},
        {"id": "c", "text": "A small file containing one commit hash"},
        {"id": "d", "text": "A list of every changed line"}], "correct_option_id": "c",
     "explanation": "A branch is a 40-character hash in a tiny file, which is why creating one is nearly free.",
     "concept_tag": "references"},
    {"id": "q5", "prompt": "What does HEAD normally contain?", "options": [
        {"id": "a", "text": "A symbolic reference to the current branch"},
        {"id": "b", "text": "The hash of the first commit"},
        {"id": "c", "text": "The list of staged files"},
        {"id": "d", "text": "A copy of the working directory"}], "correct_option_id": "a",
     "explanation": "HEAD usually holds something like ref: refs/heads/main. A raw hash means detached HEAD.",
     "concept_tag": "references"},
]}

PLAN = [
    ("Git Is a Photo Album, Not a Diff Machine",
     "A gentle tour of how Git stores snapshots and why that design makes it fast and safe.",
     ["objects", "staging", "references"], "overview_and_calibration"),
    ("Inside the Object Store",
     "Open .git/objects and watch blobs, trees and commits appear as you work.",
     ["hashing", "objects", "compression"], "standard_lesson"),
    ("The Index: Building a Commit Deliberately",
     "How staging works, partial adds, and what the index file really contains.",
     ["staging", "index-file", "partial-commits"], "standard_lesson"),
    ("Branches, HEAD and Moving Pointers",
     "Branches as references, detached HEAD, and why checkout is cheap.",
     ["references", "head", "checkout"], "standard_lesson"),
    ("Merge, Rebase and Rewriting History Safely",
     "What merge and rebase do to the commit graph, and how to recover with the reflog.",
     ["merge", "rebase", "reflog"], "standard_lesson"),
]


def seed() -> str:
    for t in workspace.list_topics():
        if t["topic"] == "How Git Really Works (sample course)":
            return t["topic_slug"]
    meta = workspace.create_topic("How Git Really Works (sample course)", "beginner")
    slug = meta["topic_slug"]
    sources.add_local_file(slug, SOURCE_NAME, SOURCE_TEXT.encode("utf-8"), allow_cloud=True)

    def mutate(m: dict) -> None:
        arch = m["curriculum_architecture"]
        arch.update(designed_by="head_brain", assumed_level="beginner",
                    audience_note="Developers who use Git daily but have never looked inside it.")
        arch["reliable_sources"] = [
            {"name": "Pro Git — Git Internals (Chacon & Straub)", "type": "textbook",
             "url_or_ref": "https://git-scm.com/book/en/v2/Git-Internals-Plumbing-and-Porcelain",
             "why": "The canonical open book by the project's maintainers.", "status": "not_allowlisted", "approved": False},
            {"name": "Your notes: git_internals_notes.md", "type": "reference",
             "url_or_ref": "uploaded file", "why": "Material you supplied.", "status": "citation_only", "approved": False},
        ]
        m["lessons"] = []
        for i, (title, summary, concepts, ltype) in enumerate(PLAN):
            lid = f"lesson_{i + 1}"
            m["lessons"].append({
                "id": lid, "type": ltype, "title": title, "summary": summary,
                "key_concepts": [schema.norm_tag(c) for c in concepts],
                "file": f"{lid}.md", "quiz_file": f"{lid}_quiz.json", "result_file": None,
                "diagram_files": ["diagrams/lesson_1_fig1.mmd"] if i == 0 else [],
                "state": "current" if i == 0 else "locked", "generated": i == 0,
                "quiz_score": None, "sources_used": ["src_1"] if i == 0 else [],
            })
        m["status"] = "in_progress"
        workspace.log_revision(m, "plan", "roadmap_created", "Head tutor designed 5 lessons around your notes.")
    workspace.update_meta(slug, mutate)
    workspace.write_text(slug, "lesson_1.md", LESSON_MD)
    workspace.write_text(slug, "diagrams/lesson_1_fig1.mmd", DIAGRAM)
    workspace.write_json(slug, "lesson_1_quiz.json", QUIZ)
    return slug
