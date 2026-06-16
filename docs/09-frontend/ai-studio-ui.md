# AI Studio UI

Phase 49. Visual interface for all workspace AI configuration. Accessible via the **AI** tab in Workspace Settings.

---

## Location

`/settings/workspaces/:slug` → **AI** tab

Same route as workspace settings — tab selection via `?tab=ai` query param or Radix `Tabs` state.

---

## Form Sections

### Persona & Prompts

Four `<textarea>` fields mapping to `scenario_prompts`:

```
Intro prompt     — fires on first message
Core prompt      — fires on all subsequent messages  
Checkout prompt  — fires during checkout flow
HITL prompt      — fires on human handover
```

Each textarea:
- `maxLength={4000}`
- Placeholder shows example prompt for that slot
- Cleared value saves `null` (falls back to global default)

### Node Configuration

Six toggle rows. Each row: icon + label + description + `<Switch>` (Radix `Switch.Root`).

Guardrails toggle shows inline warning when set to off:

```
⚠️ Disabling guardrails removes citation enforcement. For testing only.
```

### Model Parameters

- Temperature: `<Slider>` from 0.0 to 2.0, step 0.1. Current value shown as badge.
- Max tokens: `<Input type="number">` with `min=1 max=4096`
- Model: `<Select>` dropdown, options from allowlist

---

## Form State

Uses uncontrolled form with `react-hook-form`:

```jsx
const { register, handleSubmit, reset, formState } = useForm({
  defaultValues: aiSettings,
});
```

`reset(aiSettings)` called on successful GET load. Dirty state tracked via `formState.isDirty` to enable/disable the Save button.

---

## Save & Reset

**Save** — `handleSubmit` → `PUT /api/workspace/ai-settings` → success toast or error banner.

**Reset to defaults** — Confirm dialog → `PUT /api/workspace/ai-settings` with `{}` → `reset({})` to clear form.

---

## Validation

Client-side (react-hook-form):
- `temperature`: `{ min: 0, max: 2 }`
- `max_tokens`: `{ min: 1, max: 4096 }`

Server-side errors surface as field-level error messages below each input.

---

## Related Docs

- [Prompt Studio](../06-ai-customization/prompt-studio.md)
- [AI Settings Schema](../06-ai-customization/ai-settings-schema.md)
- [Workspace Settings UI](workspace-settings-ui.md)
