//
// `useFormErrors` tests: DRF 400 bodies become field and form messages;
// other failures become one form message.
//

// 3rd party imports
//
import { describe, expect, it } from "vitest";

// app imports
//
import { ApiError, AuthError } from "@/api/errors";
import { useFormErrors } from "@/composables/useFormErrors";

////////////////////////////////////////////////////////////////////////
//
function apiError(status: number, body: unknown): ApiError {
  return new ApiError(status, JSON.stringify(body));
}

////////////////////////////////////////////////////////////////////////
//
describe("useFormErrors", () => {
  // GIVEN: a 400 with field and non-field errors
  // WHEN:  it is set on the form
  // THEN:  each field gets its first message and the form gets the
  //        non-field message
  //
  it("splits a DRF 400", () => {
    const form = useFormErrors();
    form.setError(
      apiError(400, { new_password: ["Too short.", "Too common."], non_field_errors: ["No."] }),
    );
    expect(form.fieldError("new_password")).toBe("Too short.");
    expect(form.fieldError("current_password")).toBeNull();
    expect(form.formError.value).toBe("No.");
  });

  // GIVEN: a 400 with only field errors
  // WHEN:  it is set on a form that shows field messages, and on one
  //        that does not
  // THEN:  the first shows no form message; the second shows the first
  //        field message as the form message
  //
  it("surfaces field messages for forms without inline fields", () => {
    const body = { name: ["Required."] };
    const inline = useFormErrors();
    inline.setError(apiError(400, body));
    expect(inline.formError.value).toBeNull();

    const plain = useFormErrors();
    plain.setError(apiError(400, body), { inlineFields: false });
    expect(plain.formError.value).toBe("Required.");
  });

  // GIVEN: a 400 without a usable body, a 409 with a fixed message, and
  //        an ended session
  // WHEN:  each is set
  // THEN:  the fallback, the fixed message, and the session notice show
  //
  it.each([
    [new ApiError(400, "not json"), "Save failed."],
    [apiError(409, { detail: "Conflict." }), "Already invited."],
    [new AuthError(), "Your session has expired. Please sign in again."],
    [apiError(500, { detail: "Server exploded." }), "Server exploded."],
  ])("maps %s", (err, message) => {
    const form = useFormErrors();
    form.setError(err, { fallback: "Save failed.", statusMessages: { 409: "Already invited." } });
    expect(form.formError.value).toBe(message);
    expect(form.fieldErrors.value).toEqual({});
  });

  // GIVEN: a form with messages
  // WHEN:  it is cleared, or given a message directly
  // THEN:  the messages follow
  //
  it("clears and sets directly", () => {
    const form = useFormErrors();
    form.setError(apiError(400, { a: ["x"] }));
    form.clear();
    expect([form.fieldErrors.value, form.formError.value]).toEqual([{}, null]);
    form.setFormError("Required.");
    expect(form.formError.value).toBe("Required.");
  });
});
