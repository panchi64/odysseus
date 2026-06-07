import type { Upload } from "./model";

export const mockUploads: Upload[] = [
  {
    id: "u-001",
    name: "invoice_q2_2026.pdf",
    mime: "application/pdf",
    sizeBytes: 284_672,
    status: "done",
    extractedText:
      "INVOICE #2026-Q2-0042\nDate: 2026-06-01\nBill To: Odysseus Project\nDescription: Annual compute credits\nAmount: $1,200.00\nDue: 2026-07-01\n\nThank you for your business.",
    formFields: [
      { name: "Invoice Number", value: "2026-Q2-0042" },
      { name: "Due Date", value: "2026-07-01" },
      { name: "Amount", value: "$1,200.00" },
    ],
    vision: false,
  },
  {
    id: "u-002",
    name: "scanned_contract_draft.pdf",
    mime: "application/pdf",
    sizeBytes: 1_572_864,
    status: "done",
    extractedText:
      "SERVICE AGREEMENT\n\nThis agreement is entered into as of June 1, 2026 between the parties described herein. Terms and conditions apply. All rights reserved. Signature required on page 4.",
    formFields: [
      { name: "Party A", value: "" },
      { name: "Party B", value: "" },
      { name: "Effective Date", value: "2026-06-01" },
      { name: "Signature", value: "" },
    ],
    vision: true,
  },
  {
    id: "u-003",
    name: "research_paper_rag.pdf",
    mime: "application/pdf",
    sizeBytes: 3_145_728,
    status: "extracting",
    extractionProgress: 62,
    vision: false,
  },
  {
    id: "u-004",
    name: "onboarding_form.pdf",
    mime: "application/pdf",
    sizeBytes: 204_800,
    status: "queued",
    vision: false,
  },
  {
    id: "u-005",
    name: "broken_scan.pdf",
    mime: "application/pdf",
    sizeBytes: 98_304,
    status: "error",
    vision: true,
  },
];
