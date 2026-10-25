import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { anImportDetail, apiCalls, json, renderAt, stubFetch } from "./helpers";

afterEach(() => {
  vi.unstubAllGlobals();
});

function csv(name = "valid.csv") {
  return new File(["sku,name,price,quantity\n"], name, { type: "text/csv" });
}

function fillForm(vendor: string, file: File | null) {
  fireEvent.change(screen.getByRole("textbox", { name: "Vendor name" }), { target: { value: vendor } });
  if (file) fireEvent.change(screen.getByLabelText("CSV file"), { target: { files: [file] } });
}

function sentForm(call: unknown[]): FormData {
  const init = call[1] as RequestInit;
  expect(init.method).toBe("PUT");
  expect(init.body).toBeInstanceOf(FormData);
  return init.body as FormData;
}

describe("Upload page", () => {
  it("sends vendor_name, the file and inject_transient_failure, and renders the COMPLETED result", async () => {
    const fetchMock = stubFetch({
      "POST /api/imports": () => json(anImportDetail({ id: 7 }), 201),
    });
    renderAt("/upload");

    const checkbox = screen.getByRole("checkbox", { name: "Demo: fail first attempt with transient storage timeout" });
    expect(checkbox).not.toBeChecked();
    expect(screen.getByText(/synthetic/)).toBeInTheDocument();
    expect(screen.getByLabelText("CSV file")).toHaveAttribute("accept", ".csv");
    const vendorInput = screen.getByRole("textbox", { name: "Vendor name" });
    expect(vendorInput).not.toHaveAttribute("maxLength");
    expect(vendorInput).not.toBeRequired();

    const file = csv();
    fillForm("  sample furnishings  ", file);
    fireEvent.click(screen.getByRole("button", { name: "Import" }));

    const result = await screen.findByTestId("import-result");
    let form = sentForm(apiCalls(fetchMock)[0]);
    expect(apiCalls(fetchMock)[0][0]).toBe("/api/imports");
    expect(form.get("vendor_name")).toBe("  sample furnishings  ");
    expect((form.get("file") as File).name).toBe("valid.csv");
    expect(form.get("inject_transient_failure")).toBe("false");

    expect(result).toHaveTextContent("COMPLETED");
    expect(result).toHaveTextContent("Sample Furnishings"); // from the response, not the typed text
    expect(result).toHaveTextContent("valid.csv");
    expect(screen.getByRole("link", { name: "View import 7" })).toHaveAttribute("href", "/imports/7");

    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    await vi.waitFor(() => expect(apiCalls(fetchMock)).toHaveLength(2));
    form = sentForm(apiCalls(fetchMock)[1]);
    expect(form.get("inject_transient_failure")).toBe("true");
    await screen.findByTestId("import-result");
  });

  it("renders a FAILED 201 with VALIDATION_ERROR, the line errors and the link", async () => {
    stubFetch({
      "POST /api/imports": () =>
        json(
          anImportDetail({
            id: 9,
            filename: "invalid.csv",
            status: "FAILED",
            failure_code: "VALIDATION_ERROR",
            product_count: null,
            completed_at: null,
            validation_errors: [
              { line: 4, column: "quantity", message: "must be a whole number of up to 9 digits, got '-2'" },
            ],
            validation_error_count: 1,
          }),
          201,
        ),
    });
    renderAt("/upload");

    fillForm("Sample Furnishings", csv("invalid.csv"));
    fireEvent.click(screen.getByRole("button", { name: "Import" }));

    const result = await screen.findByTestId("import-result");
    expect(result).toHaveTextContent("FAILED");
    expect(result).toHaveTextContent("VALIDATION_ERROR");
    expect(screen.getByText("line 4, quantity: must be a whole number of up to 9 digits, got '-2'")).toBeInTheDocument();
    expect(screen.getByText("1 error")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View import 9" })).toHaveAttribute("href", "/imports/9");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders a 413 as FILE_TOO_LARGE in an alert with no result and no link", async () => {
    stubFetch({
      "POST /api/imports": () => json({ code: "FILE_TOO_LARGE", message: "CSV exceeds 256 KiB", details: [] }, 413),
    });
    renderAt("/upload");

    fillForm("Sample Furnishings", csv("big.csv"));
    fireEvent.click(screen.getByRole("button", { name: "Import" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("FILE_TOO_LARGE: CSV exceeds 256 KiB");
    expect(screen.queryByTestId("import-result")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /View import/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import" })).toBeEnabled();
  });

  it("omits the file part when none is chosen and sends one request for two quick clicks", async () => {
    let release: () => void = () => {};
    const fetchMock = stubFetch({
      "POST /api/imports": () =>
        new Promise<Response>((resolve) => {
          release = () => resolve(json({ code: "MISSING_FIELD", message: "file is required", details: [] }, 400));
        }),
    });
    renderAt("/upload");

    fillForm("Sample Furnishings", null);
    const button = screen.getByRole("button", { name: "Import" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(button).toBeDisabled();
    await vi.waitFor(() => expect(apiCalls(fetchMock)).toHaveLength(1));

    release();
    expect(await screen.findByRole("alert")).toHaveTextContent("MISSING_FIELD: file is required");
    expect(apiCalls(fetchMock)).toHaveLength(1);
    expect(sentForm(apiCalls(fetchMock)[0]).has("file")).toBe(false);
    expect(button).toBeEnabled();
  });
});
