
class ReportPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(150,150,150)
        self.cell(0, 8, "Crypto Liquidity Finder -- Research Report", align="C", new_x="LMARGIN", new_y="NEXT")
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120,120,120)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}} | {REPORT_DATE}", align="C")
    def stitle(self, t):
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(33,150,243)
        self.cell(0, 10, t, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(33,150,243)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)
    def sub(self, t):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(200,200,200)
        self.cell(0, 8, t, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)
    def txt(self, s):
        self.set_font("Helvetica", "", 9)
        self.set_text_color(180,180,180)
        self.multi_cell(0, 5, s)
        self.ln(1)
    def bul(self, s):
        self.set_font("Helvetica", "", 9)
        self.set_text_color(180,180,180)
        self.cell(12, 5, "")
        self.set_text_color(33,150,243)
        self.cell(4, 5, "-")
        self.set_text_color(180,180,180)
        self.multi_cell(0, 5, s)
        self.ln(1)
    def chart(self, path, w=180):
        if path and os.path.exists(path):
            self.image(path, x=15, w=w)
            self.ln(2)
    def thdr(self, cols, ws):
        self.set_font("Helvetica", "B", 7.5)
        self.set_text_color(200,200,200)
        self.set_fill_color(40,40,40)
        for c,w in zip(cols,ws):
            self.cell(w, 6, c, border=1, align="C", fill=True)
        self.ln()
    def trow(self, vals, ws):
        self.set_font("Helvetica", "", 7)
        self.set_text_color(180,180,180)
        for v,w in zip(vals,ws):
            self.cell(w, 5, v, border=1, align="C")
        self.ln()

print("PDF class ready")
