import re
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment
from pathlib import Path


def save_excel(output: str, output_dir: str, output_filename: str):
    # Adjusted pattern to match NetCTLpan output columns
    table_pattern = re.compile(
        r"^\s*(\d+)\s+([^\s]+)\s+([^\s]+)\s+([A-Za-z]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.]+)\s*(<-E)?",
        re.MULTILINE
    )
    matches = table_pattern.findall(output)

    # Define columns based on NetCTLpan output
    columns = ["N", "Sequence Name", "Allele", "Peptide",
               "MHC", "TAP", "Cle", "Comb", "%Rank", "Epitope"]
    df = pd.DataFrame(matches, columns=columns)

    # Convert numeric columns to appropriate types
    numeric_cols = ["N", "MHC", "TAP", "Cle", "Comb", "%Rank"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col])

    # Replace empty epitope field with "" instead of NaN
    df["Epitope"] = df["Epitope"].fillna("")

    # Extract summary line (e.g., "Number of MHC ligands...")
    summary_pattern = re.compile(r"Number of MHC ligands.*")
    summary_match = summary_pattern.findall(output)

    # Add summary as a new row if found
    if summary_match:
        summary_row = [summary_match[0]] + [""] * (len(columns) - 1)
        df.loc[len(df)] = summary_row

    # Define output file path
    output_path = Path(output_dir) / output_filename

    # Write to Excel
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name="Results", index=False)

        # Get workbook and worksheet objects
        workbook = writer.book
        worksheet = writer.sheets["Results"]

        # If summary exists, merge the last row's cells and center the text
        if summary_match:
            worksheet.merge_cells(start_row=len(
                df) + 1, start_column=1, end_row=len(df) + 1, end_column=len(columns))
            cell = worksheet.cell(row=len(df) + 1, column=1)
            cell.alignment = Alignment(horizontal='center', vertical='center')

    # Save the workbook
    workbook.save(output_path)
    # print(f"Excel file saved to: {output_path}")
