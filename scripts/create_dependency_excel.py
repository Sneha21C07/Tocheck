"""
Script to generate the repository dependency mapping Excel file.
Creates repo_dependency_mapping.xlsx with formatted headers, validation, and sample rows.
"""

from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

OUTPUT_FILE = Path(__file__).resolve().parent.parent / "repo_dependency_mapping.xlsx"

HEADERS = [
    "Pair_ID",
    "Source_Repo",
    "Source_Branch",
    "Source_File_Pattern",
    "Target_Repo",
    "Target_Branch",
    "Target_File_Pattern",
    "Dependency_Type",
    "Severity_Level",
    "Notification_Channel",
    "Auto_Block_PR",
    "Owner_Team",
    "Description",
]

SAMPLE_DATA = [
    [
        "DEP-001",
        "sample-org/order-service",
        "main",
        "**/dto/**/*.java, **/api/**/*.java",
        "sample-org/payment-service",
        "main",
        "**/client/**/*.java, **/consumer/**/*.java",
        "REST_API_CONSUMER",
        "CRITICAL",
        "PR_COMMENT",
        "TRUE",
        "Checkout-Team",
        "Payment service invokes Order API; changes to OrderDTO or /orders endpoint break billing.",
    ],
    [
        "DEP-002",
        "sample-org/user-service",
        "main",
        "**/events/**/*.java, **/model/**/*.java",
        "sample-org/notification-service",
        "main",
        "**/listener/**/*.java, **/model/**/*.java",
        "EVENT_PAYLOAD_SCHEMA",
        "HIGH",
        "PR_COMMENT",
        "FALSE",
        "Engagement-Team",
        "UserRegisteredEvent and UserProfileUpdatedEvent Kafka payloads consumed by notification-service.",
    ],
    [
        "DEP-003",
        "sample-org/inventory-service",
        "main",
        "**/dto/StockCheckResponse.java",
        "sample-org/order-service",
        "main",
        "**/client/InventoryClient.java",
        "RPC_INTERFACE",
        "HIGH",
        "PR_COMMENT",
        "TRUE",
        "Logistics-Team",
        "Order service checks stock inventory before confirming checkout.",
    ],
    [
        "DEP-004",
        "Sneha21C07/Tocheck",
        "main",
        "**/dto/**/*.java, **/controller/**/*.java",
        "sample-org/repo2-user-update-service",
        "main",
        "**/dto/**/*.java, **/controller/**/*.java",
        "SHARED_DTO",
        "CRITICAL",
        "PR_COMMENT",
        "TRUE",
        "Identity-Team",
        "Repo 2 updates user profiles created by Repo 1. Changes to UserDTO fields or endpoints break data consistency.",
    ],
]


def generate_excel(file_path: Path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Repo_Dependencies"

    # Color Palette: Corporate Navy / Slate
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Segoe UI", size=10)
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center", wrap_text=True)

    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )

    # Write Headers
    ws.row_dimensions[1].height = 28
    for col_idx, header in enumerate(HEADERS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_align
        cell.border = thin_border

    # Write Sample Rows
    for row_idx, row_data in enumerate(SAMPLE_DATA, start=2):
        ws.row_dimensions[row_idx].height = 32
        for col_idx, value in enumerate(row_data, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = data_font
            cell.border = thin_border
            if col_idx in (1, 3, 6, 8, 9, 10, 11):
                cell.alignment = center_align
            else:
                cell.alignment = left_align

            # Subtle alternating row fill
            if row_idx % 2 == 1:
                cell.fill = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid")

    # Set column widths
    column_widths = {
        1: 12,   # Pair_ID
        2: 28,   # Source_Repo
        3: 15,   # Source_Branch
        4: 36,   # Source_File_Pattern
        5: 30,   # Target_Repo
        6: 15,   # Target_Branch
        7: 36,   # Target_File_Pattern
        8: 22,   # Dependency_Type
        9: 16,   # Severity_Level
        10: 20,  # Notification_Channel
        11: 15,  # Auto_Block_PR
        12: 20,  # Owner_Team
        13: 45,  # Description
    }

    for col_idx, width in column_widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.freeze_panes = "A2"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(file_path)
    print(f"Excel dependency mapping generated at: {file_path}")


if __name__ == "__main__":
    generate_excel(OUTPUT_FILE)
