# AGENTS.md

## 1. System Constraints & Tech Stack
- **Terminal First**: All build, test, and run commands must work directly in a standard shell (`bash` or `zsh`).
- **Zero Heavy Dependencies**: Rely strictly on out-of-the-box (OOTB) standard libraries, core tools, and native APIs. Avoid complex UI component frameworks or unneeded third-party libraries.
- **Code Quality**: Keep scripts simple, self-contained, and easy to run from the command line.

---

## 2. Planning Protocol (Senior Product Manager Standards)
When asked to build a new feature, fix a bug, or refactor code, follow these steps before editing production code:

1. **Understand Problem & Value**: Briefly state the user problem, target goal, and definition of success.
2. **Inspect Existing Code**: Search the repository to understand current behavior, risks, and dependencies.
3. **Write `PLAN.md`**: Create or update a temporary file named `PLAN.md` at the project root containing:
   - **Problem Statement**: Clear definition of what needs solving.
   - **Functional Scope**: What is included in this task, and what is explicitly excluded.
   - **Technical Strategy**: Summary of the chosen approach using standard, built-in tools.
   - **Step-by-Step Task Checklist**: Ordered list of small, actionable execution steps (`[ ] Task`).
   - **Risk & Edge Cases**: Potential failure modes, data loss risks, or breaking changes.
4. **Pause for Review**: Ask the user to inspect and approve `PLAN.md` before making code edits.

---

## 3. Execution Protocol (Senior Developer Standards)
When the user approves `PLAN.md` or says "Execute":

1. **Work in Small Steps**: Implement changes one task at a time following `PLAN.md`.
2. **Keep Diffs Clean**: Write clean, readable code with zero dead code, zero unnecessary abstractions, and minimal external changes.
3. **Native Error Handling**: Implement clear error messages and safe exit codes for terminal execution.
4. **Automated Local Testing**:
   - Run native compiler/interpreter syntax checks (for example, `python -m py_compile` or `go vet` or `tsc --noEmit`).
   - Run relevant test suites via the shell.
5. **Update Progress**: Mark finished items in `PLAN.md` from `[ ]` to `[x]` as you complete them.
6. **Final Gate**: Ensure all tests pass cleanly before marking the task complete.
