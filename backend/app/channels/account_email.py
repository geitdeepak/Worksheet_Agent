"""The email a parent receives when an administrator adds them (or sets a new password): where to sign in, the
login details, and which children they can make practice sheets for. Same look as the worksheet email."""
from html import escape

from sqlalchemy.orm import Session

from ..services.common import get_setting
from .email_template import ACCENT, INK, LINE, MUTED, NAVY, SOFT


def render_parent_login(db: Session, name: str, email: str, password: str, children: list[str], login_url: str,
                        new_account: bool = True) -> tuple[str, str, str]:
    """Returns (subject, plain text, html)."""
    inst = get_setting(db, "institution_name") or "Practice Sheet Agent"
    kids = ", ".join(children) or "your child"
    if new_account:
        subject = f"Your login for practice sheets – {inst}"
        intro = (f"{inst} has created an account for you. You can now make practice sheets for <b>{escape(kids)}</b> "
                 "whenever you like: choose a subject (and chapters, if you want), and download the sheet as a PDF with an "
                 "answer key.")
    else:
        subject = f"Your new password for practice sheets – {inst}"
        intro = f"{inst} has set a new password for your account. Your login details are below."
    rows = [("Sign in at", login_url), ("Email", email), ("Password", password), ("Children", kids)]
    steps = [f"Open {login_url} and sign in with the email and password above.",
             "Choose your child, a subject and, if you like, particular chapters.",
             "Click “Make practice sheet”. After a minute or two it appears in your list: download the PDF.",
             "For your security, change your password after you sign in (under “Your password” on your page)."]
    footer = (f"You received this email because {inst} added you as a parent. If you did not expect it, "
              "please contact the school.")

    text = "\n".join([f"Dear {name},", "", intro.replace("<b>", "").replace("</b>", ""), "", "YOUR LOGIN DETAILS",
                      *[f"  {k}: {v}" for k, v in rows], "", "HOW IT WORKS", *[f"  {i}. {s}" for i, s in enumerate(steps, 1)],
                      "", "Best regards,", inst, "", "—", footer])

    font = "'Segoe UI', Roboto, Arial, 'Nirmala UI', 'Noto Sans Devanagari', sans-serif"
    detail_rows = "".join(
        f'<tr><td style="padding:8px 12px;color:{MUTED};font-size:13px;width:32%;border-top:1px solid {LINE};">{escape(k)}</td>'
        f'<td style="padding:8px 12px;color:{INK};font-size:14px;font-weight:600;border-top:1px solid {LINE};'
        f'{"font-family:Consolas,Menlo,monospace;" if k == "Password" else ""}word-break:break-all;">{escape(v)}</td></tr>'
        for k, v in rows)
    step_rows = "".join(
        f'<tr><td style="width:28px;vertical-align:top;padding:4px 0;"><span style="display:inline-block;width:22px;height:22px;'
        f'line-height:22px;border-radius:11px;background:{ACCENT};color:#ffffff;font-size:12px;font-weight:700;text-align:center;">{i}</span></td>'
        f'<td style="padding:4px 0 4px 6px;color:{INK};font-size:14px;line-height:21px;">{escape(s)}</td></tr>'
        for i, s in enumerate(steps, 1))
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f4f6fb;font-family:{font};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6fb;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid {LINE};">
  <tr><td style="background:{NAVY};background-image:linear-gradient(135deg,{NAVY} 0%,{ACCENT} 100%);padding:22px 28px;">
    <div style="color:#ffffff;font-size:13px;letter-spacing:.06em;text-transform:uppercase;opacity:.85;">{escape(inst)}</div>
    <div style="color:#ffffff;font-size:22px;font-weight:700;line-height:30px;margin-top:4px;">{escape(subject)}</div>
  </td></tr>
  <tr><td style="padding:26px 28px 8px;">
    <p style="margin:0 0 12px;color:{INK};font-size:16px;font-weight:600;">Dear {escape(name)},</p>
    <p style="margin:0 0 20px;color:{INK};font-size:15px;line-height:23px;">{intro}</p>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{SOFT};border-radius:10px;border:1px solid {LINE};">
      <tr><td colspan="2" style="padding:10px 12px;color:{NAVY};font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;">Your login details</td></tr>
      {detail_rows}
    </table>
    <table role="presentation" cellpadding="0" cellspacing="0" style="margin:22px 0 4px;"><tr>
      <td style="background:{ACCENT};border-radius:8px;"><a href="{escape(login_url)}" style="display:inline-block;padding:11px 22px;color:#ffffff;font-size:15px;font-weight:700;text-decoration:none;">Sign in</a></td>
    </tr></table>
    <p style="margin:22px 0 8px;color:{NAVY};font-size:15px;font-weight:700;">How it works</p>
    <table role="presentation" cellpadding="0" cellspacing="0">{step_rows}</table>
    <p style="margin:22px 0 0;color:{INK};font-size:14px;line-height:21px;">Best regards,<br><b>{escape(inst)}</b></p>
  </td></tr>
  <tr><td style="padding:18px 28px 22px;">
    <div style="border-top:1px solid {LINE};padding-top:14px;color:{MUTED};font-size:12px;line-height:18px;">{escape(footer)}</div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""
    return subject, text, html
