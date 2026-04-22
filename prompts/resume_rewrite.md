# Resume Rewrite Prompt

Rewrite resume content for a target job using ONLY facts supported by the truth model.

Constraints:
- Do not invent metrics, dates, tools, responsibilities, or business outcomes.
- You may reorder, compress, and rephrase.
- Keep tone senior, concrete, and technical.
- Prefer bullets that map to the target role's backend/system needs.
- Mirror the job description language where appropriate.

Output JSON:
{
  "summary": "...",
  "selected_bullets": ["...", "..."],
  "notes": ["..."]
}
