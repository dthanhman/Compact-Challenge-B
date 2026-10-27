# Dựng báo cáo final: body.docx (pandoc) → thêm bìa, mục lục, header/footer, định dạng → .docx + .pdf
param(
    [string]$Body = "$PSScriptRoot\tmp\body.docx",
    [string]$Logo = "$PSScriptRoot\tmp\logo-000.png",
    [string]$OutBase = "$PSScriptRoot\Group44_SE373.R11_BTVN7_ChallengeB"
)
$ErrorActionPreference = "Stop"
$FONT = "Times New Roman"

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($Body)

    # ---------- trang A4, lề
    foreach ($s in $doc.Sections) {
        $s.PageSetup.PaperSize = 7          # wdPaperA4
        $s.PageSetup.TopMargin = $word.CentimetersToPoints(2)
        $s.PageSetup.BottomMargin = $word.CentimetersToPoints(2)
        $s.PageSetup.LeftMargin = $word.CentimetersToPoints(2.5)
        $s.PageSetup.RightMargin = $word.CentimetersToPoints(2)
    }

    # ---------- style
    foreach ($name in @("Normal", "Body Text", "First Paragraph", "Compact")) {
        try {
            $st = $doc.Styles.Item($name)
            $st.Font.Name = $FONT; $st.Font.Size = 13
            if ($name -ne "Compact") { $st.ParagraphFormat.SpaceAfter = 6; $st.ParagraphFormat.LineSpacingRule = 0 }
        } catch {}
    }
    try { $doc.Styles.Item("Body Text").ParagraphFormat.Alignment = 3; $doc.Styles.Item("First Paragraph").ParagraphFormat.Alignment = 3 } catch {}
    $hs = @{ 1 = 16; 2 = 14; 3 = 13 }
    foreach ($lvl in 1..3) {
        $st = $doc.Styles.Item(-1 - $lvl)  # wdStyleHeading1 = -2 ...
        $st.Font.Name = $FONT; $st.Font.Size = $hs[$lvl]; $st.Font.Bold = $true
        $st.Font.Color = 8388608            # xanh đậm (navy)
        $st.Font.Italic = ($lvl -eq 3)
        $st.ParagraphFormat.SpaceBefore = 12; $st.ParagraphFormat.SpaceAfter = 6
        $st.ParagraphFormat.KeepWithNext = $true
    }
    try { $st = $doc.Styles.Item("Source Code"); $st.Font.Name = "Consolas"; $st.Font.Size = 9
          $st.ParagraphFormat.Shading.BackgroundPatternColor = 15987699 } catch {}
    try { $doc.Styles.Item("Verbatim Char").Font.Name = "Consolas"; $doc.Styles.Item("Verbatim Char").Font.Size = 11 } catch {}
    try { $st = $doc.Styles.Item("Image Caption"); $st.Font.Name = $FONT; $st.Font.Size = 11; $st.Font.Italic = $true
          $st.ParagraphFormat.Alignment = 1; $st.ParagraphFormat.SpaceAfter = 12 } catch {}
    foreach ($name in @("Captioned Figure", "Figure")) { try { $doc.Styles.Item($name).ParagraphFormat.Alignment = 1 } catch {} }
    foreach ($name in @("Block Text")) { try { $st = $doc.Styles.Item($name); $st.Font.Name = $FONT; $st.Font.Size = 12; $st.Font.Italic = $true } catch {} }

    # ---------- bảng: viền, hàng tiêu đề, vừa khổ trang
    foreach ($t in $doc.Tables) {
        $t.Borders.Enable = 1
        $t.Range.Font.Size = 10.5
        $t.Range.ParagraphFormat.SpaceAfter = 0
        $t.Range.ParagraphFormat.Alignment = 0
        $t.Rows.Item(1).Range.Font.Bold = $true
        $t.Rows.Item(1).Shading.BackgroundPatternColor = 15132390   # xám nhạt
        $t.Rows.Item(1).HeadingFormat = $true
        $t.AutoFitBehavior(1)   # theo nội dung
        $t.AutoFitBehavior(2)   # rồi kéo vừa khổ trang
    }
    foreach ($ish in $doc.InlineShapes) { $ish.Range.ParagraphFormat.Alignment = 1 }

    # ---------- chèn 2 section ở đầu: bìa + mục lục
    $r = $doc.Range(0, 0); $r.InsertBreak(2)   # wdSectionBreakNextPage
    $r = $doc.Range(0, 0); $r.InsertBreak(2)
    foreach ($i in 1..2) { $doc.Sections.Item($i).Range.Style = $doc.Styles.Item("Normal") }

    # --- bìa
    $lines = @(
        "ĐẠI HỌC QUỐC GIA THÀNH PHỐ HỒ CHÍ MINH",
        "TRƯỜNG ĐẠI HỌC CÔNG NGHỆ THÔNG TIN",
        "KHOA CÔNG NGHỆ PHẦN MỀM",
        "",
        "",
        "MÔN KỸ THUẬT XÂY DỰNG HỆ THỐNG AGENTIC AI",
        "BÀI TẬP THỰC HÀNH 7 - Challenge B",
        "Context Management: Compaction & Code Mode",
        "Sinh viên thực hiện:  Lữ Kim Luân - 24521028",
        "Hồ Hoàng Luân - 24521026 (Nhóm trưởng)",
        "Hồ Đình Long - 24520997",
        "Đào Thanh Mân - 24521039",
        "Tp. Hồ Chí Minh, 10/2026"
    )
    $r = $doc.Sections.Item(1).Range; $r.MoveEnd(1, -1) | Out-Null
    $r.Text = ($lines -join "`r")
    $ps = $doc.Sections.Item(1).Range.Paragraphs
    foreach ($i in 1..$lines.Count) {
        $p = $ps.Item($i)
        $p.Alignment = 1; $p.SpaceAfter = 4; $p.SpaceBefore = 0
        $p.Range.Font.Name = $FONT; $p.Range.Font.Size = 13; $p.Range.Font.Bold = $false; $p.Range.Font.Italic = $false
    }
    foreach ($i in 1..3) { $ps.Item($i).Range.Font.Bold = $true; $ps.Item($i).Range.Font.Size = 14 }
    $ps.Item(3).Borders.Item(-3).LineStyle = 1   # gạch dưới tên khoa (wdBorderBottom)
    $ps.Item(3).RightIndent = $word.CentimetersToPoints(3); $ps.Item(3).LeftIndent = $word.CentimetersToPoints(3)
    $ps.Item(4).SpaceBefore = 70
    $doc.InlineShapes.AddPicture($Logo, $false, $true, $ps.Item(4).Range) | Out-Null
    $pic = $ps.Item(4).Range.InlineShapes.Item(1); $pic.LockAspectRatio = -1; $pic.Width = $word.CentimetersToPoints(5)
    $ps.Item(6).SpaceBefore = 80
    foreach ($i in 6..7) { $ps.Item($i).Range.Font.Bold = $true; $ps.Item($i).Range.Font.Size = 18; $ps.Item($i).SpaceAfter = 10 }
    $ps.Item(8).Range.Font.Italic = $true; $ps.Item(8).Range.Font.Size = 14
    $ps.Item(9).SpaceBefore = 40
    $ps.Item(13).SpaceBefore = 60
    $sec1 = $doc.Sections.Item(1)
    $sec1.Borders.Enable = 1
    foreach ($b in -1, -2, -3, -4) {
        $bd = $sec1.Borders.Item($b); $bd.LineStyle = 13; $bd.LineWidth = 36; $bd.Color = 8388608  # thin-thick, 4.5pt, navy
    }
    $sec1.Borders.DistanceFrom = 1   # đo từ mép trang
    foreach ($b in -1, -2, -3, -4) { }
    $sec1.Borders.DistanceFromTop = 24; $sec1.Borders.DistanceFromBottom = 24
    $sec1.Borders.DistanceFromLeft = 24; $sec1.Borders.DistanceFromRight = 24

    # --- mục lục
    $r = $doc.Sections.Item(2).Range; $r.MoveEnd(1, -1) | Out-Null
    $r.Text = "MỤC LỤC`r"
    $p = $doc.Sections.Item(2).Range.Paragraphs.Item(1)
    $p.Alignment = 1; $p.Range.Font.Name = $FONT; $p.Range.Font.Size = 16; $p.Range.Font.Bold = $true; $p.SpaceAfter = 12
    $r = $doc.Sections.Item(2).Range.Paragraphs.Item(2).Range; $r.Collapse(1)
    $doc.TablesOfContents.Add($r, $true, 1, 3) | Out-Null
    foreach ($lvl in 1..3) { try { $st = $doc.Styles.Item(-19 - $lvl); $st.Font.Name = $FONT; $st.Font.Size = 12; $st.ParagraphFormat.SpaceAfter = 2; $st.ParagraphFormat.SpaceBefore = 0 } catch {} }  # TOC 1..3

    # ---------- header/footer từ section 2 (bìa không có)
    $sec2 = $doc.Sections.Item(2)
    foreach ($kind in 1) {
        $h = $sec2.Headers.Item($kind); $h.LinkToPrevious = $false
        $h.Range.Text = "SE373.R11 - Kỹ thuật xây dựng hệ thống Agentic AI"
        $h.Range.Font.Name = $FONT; $h.Range.Font.Size = 12; $h.Range.Font.Bold = $true
        $f = $sec2.Footers.Item($kind); $f.LinkToPrevious = $false
        $f.Range.Text = ""
        $f.Range.ParagraphFormat.Alignment = 2
        $f.Range.Fields.Add($f.Range, 33) | Out-Null   # PAGE
        $f.Range.InsertAfter(" | Page")
        $f.Range.Font.Name = $FONT; $f.Range.Font.Size = 11
        $f.Range.ParagraphFormat.Borders.Item(-1).LineStyle = 1   # gạch trên footer
    }
    $doc.Sections.Item(1).Headers.Item(1).Range.Text = ""
    $doc.Sections.Item(1).Footers.Item(1).Range.Text = ""

    $doc.TablesOfContents.Item(1).Update()
    $doc.Fields.Update() | Out-Null

    $doc.SaveAs2("$OutBase.docx", 16)          # wdFormatDocumentDefault
    $doc.ExportAsFixedFormat("$OutBase.pdf", 17) # wdExportFormatPDF
    "pages: " + $doc.ComputeStatistics(2)
    $doc.Close($false)
} finally {
    $word.Quit()
}
