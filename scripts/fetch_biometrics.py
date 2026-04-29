#!/usr/bin/env python3
"""
Daily biometrics data fetcher for the impact dashboard.
Writes biometrics_data.json to the repo root.
Runs via GitHub Actions every morning at 8 AM IST (2:30 UTC).

Required env vars: AMPLITUDE_API_KEY, AMPLITUDE_SECRET_KEY
"""
import base64, json, os, requests
from datetime import date, timedelta, datetime, timezone

API_KEY = os.environ["AMPLITUDE_API_KEY"]
SECRET  = os.environ["AMPLITUDE_SECRET_KEY"]
BASE    = "https://amplitude.com/api/2"

_token  = base64.b64encode(f"{API_KEY}:{SECRET}".encode()).decode()
HEADERS = {"Authorization": f"Basic {_token}", "Accept": "application/json"}

LAUNCH_DATE  = "20260420"
BEFORE_START = "20260324"
BEFORE_END   = "20260419"
BEFORE_DAYS  = 27
BUG_FIX_DATE = "20260428"   # iOS biometrics bug fixed


def _after_end():
    """Yesterday — ensures the day is fully complete in Amplitude."""
    return (date.today() - timedelta(days=1)).strftime("%Y%m%d")

def _after_days(end_str):
    launch = date(2026, 4, 20)
    end    = date(int(end_str[:4]), int(end_str[4:6]), int(end_str[6:]))
    return max(1, (end - launch).days + 1)


def _seg(event, start, end, group_by=None, interval=1):
    params = {
        "e":     json.dumps({"event_type": event}),
        "start": start, "end": end,
        "m":     "totals", "i": interval,
    }
    if group_by:
        params["g"] = group_by
    try:
        r = requests.get(f"{BASE}/events/segmentation", params=params,
                         headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"  WARN {event}[{group_by or 'total'}]: HTTP {r.status_code}")
            return None
        return r.json().get("data", {})
    except Exception as e:
        print(f"  ERROR {event}: {e}")
        return None


def total(event, start, end):
    data = _seg(event, start, end)
    if not data: return 0
    series = data.get("series", [[]])
    return int(sum(series[0])) if series else 0


def daily_overall(event, start, end):
    """Returns (dates_list, values_list)."""
    data = _seg(event, start, end)
    if not data: return [], []
    return data.get("xValues", []), [int(v) for v in data.get("series", [[]])[0]]


def daily_by_platform(event, start, end):
    """Returns {platform: [int_values], 'dates': [date_strs]}."""
    data = _seg(event, start, end, group_by="platform")
    if not data: return {"dates": []}
    xvals  = data.get("xValues", [])
    series = data.get("series", [])
    labels = data.get("seriesLabels", [])
    result = {"dates": xvals}
    for lbl, vals in zip(labels, series):
        plat = lbl[0] if isinstance(lbl, list) else str(lbl)
        result[plat] = [int(v) for v in vals]
    return result


def platform_total(event, start, end):
    d = dict(daily_by_platform(event, start, end))
    d.pop("dates", None)
    return {p: int(sum(v)) for p, v in d.items()}


def _get(d, plat):
    return d.get(plat, d.get(plat.lower(), 0))


def main():
    end   = _after_end()
    adays = _after_days(end)
    print(f"Fetching: {LAUNCH_DATE} → {end}  ({adays} days post-launch)")

    # ── 1. Setup funnel (overall) ────────────────────────────────────
    print("[1] Setup funnel...")
    screen_views  = total("BIOMETRIC_SETUP_SCREEN_VIEW",      LAUNCH_DATE, end)
    enrolled      = total("SECURITY_BIOMETRICS_ENABLED",       LAUNCH_DATE, end)
    deferred      = total("SECURITY_SETUP_SKIPPED",            LAUNCH_DATE, end)
    enroll_failed = total("SECURITY_BIOMETRICS_ENABLE_FAILED", LAUNCH_DATE, end)
    enrollment_rate = round(enrolled / screen_views * 100, 1) if screen_views else 0

    # ── 2. Login funnel (overall) ────────────────────────────────────
    print("[2] Login funnel...")
    clicked   = total("BIOMETRIC_LOGIN_CLICKED",            LAUNCH_DATE, end)
    verified  = total("BIOMETRIC_LOGIN_CHALLENGE_VERIFIED", LAUNCH_DATE, end)
    os_failed = total("BIOMETRIC_VERIFY_FAILED",            LAUNCH_DATE, end)
    bk_failed = total("BIOMETRIC_LOGIN_CHALLENGE_FAILED",   LAUNCH_DATE, end)
    fallback  = total("BIOMETRIC_VERIFY_FALLBACK_TO_PIN",   LAUNCH_DATE, end)
    success_rate = round(verified / clicked * 100, 1) if clicked else 0

    # ── 3. Platform breakdown ────────────────────────────────────────
    print("[3] Platform breakdown...")
    p_screen = platform_total("BIOMETRIC_SETUP_SCREEN_VIEW",       LAUNCH_DATE, end)
    p_enroll = platform_total("SECURITY_BIOMETRICS_ENABLED",        LAUNCH_DATE, end)
    p_defer  = platform_total("SECURITY_SETUP_SKIPPED",             LAUNCH_DATE, end)
    p_efail  = platform_total("SECURITY_BIOMETRICS_ENABLE_FAILED",  LAUNCH_DATE, end)
    p_click  = platform_total("BIOMETRIC_LOGIN_CLICKED",            LAUNCH_DATE, end)
    p_verify = platform_total("BIOMETRIC_LOGIN_CHALLENGE_VERIFIED", LAUNCH_DATE, end)
    p_osfail = platform_total("BIOMETRIC_VERIFY_FAILED",            LAUNCH_DATE, end)
    p_fback  = platform_total("BIOMETRIC_VERIFY_FALLBACK_TO_PIN",   LAUNCH_DATE, end)

    def plat_obj(plat):
        sv = _get(p_screen, plat); en = _get(p_enroll, plat)
        cl = _get(p_click,  plat); vr = _get(p_verify, plat)
        os = _get(p_osfail, plat)
        return {
            "screen_views":      sv,
            "enrolled":          en,
            "deferred":          _get(p_defer, plat),
            "enroll_failed":     _get(p_efail, plat),
            "enrollment_rate":   round(en / sv * 100, 1) if sv else 0,
            "login_clicks":      cl,
            "login_verified":    vr,
            "os_failed":         os,
            "pin_fallback":      _get(p_fback, plat),
            "login_success_rate": round(vr / cl * 100, 1) if cl else 0,
            "os_fail_rate":       round(os / cl * 100, 1) if cl else 0,
        }

    platform = {"iOS": plat_obj("iOS"), "Android": plat_obj("Android")}

    # ── 4. Daily overall ─────────────────────────────────────────────
    print("[4] Daily overall trends...")
    dates, d_enrolled = daily_overall("SECURITY_BIOMETRICS_ENABLED",        LAUNCH_DATE, end)
    _,     d_logins   = daily_overall("BIOMETRIC_LOGIN_CHALLENGE_VERIFIED",  LAUNCH_DATE, end)
    _,     d_otp      = daily_overall("VERIFY_OTP_SUCCESS",                  LAUNCH_DATE, end)
    _,     d_signups  = daily_overall("SETUP_SECURE_PIN_SUCCESS",            LAUNCH_DATE, end)

    # ── 5. Daily platform failure rates ──────────────────────────────
    print("[5] Daily iOS/Android failure rates...")
    d_click  = daily_by_platform("BIOMETRIC_LOGIN_CLICKED", LAUNCH_DATE, end)
    d_osfail = daily_by_platform("BIOMETRIC_VERIFY_FAILED", LAUNCH_DATE, end)

    pdates      = d_click.get("dates", list(dates))
    ios_clicks  = d_click.get("iOS",     [0]*len(pdates))
    and_clicks  = d_click.get("Android", [0]*len(pdates))
    ios_fails   = d_osfail.get("iOS",    [0]*len(pdates))
    and_fails   = d_osfail.get("Android",[0]*len(pdates))

    def fail_rate(fails, clicks):
        return [round(f/c*100, 1) if c else None for f, c in zip(fails, clicks)]

    # ── 6. Before vs after ───────────────────────────────────────────
    print("[6] Before vs after...")
    signin_before = total("SIGNIN_PAGE_VIEW",         BEFORE_START, BEFORE_END)
    signin_after  = total("SIGNIN_PAGE_VIEW",         LAUNCH_DATE,  end)
    otp_before    = total("VERIFY_OTP_SUCCESS",       BEFORE_START, BEFORE_END)
    otp_after     = total("VERIFY_OTP_SUCCESS",       LAUNCH_DATE,  end)
    signup_before = total("SETUP_SECURE_PIN_SUCCESS", BEFORE_START, BEFORE_END)
    signup_after  = total("SETUP_SECURE_PIN_SUCCESS", LAUNCH_DATE,  end)

    cr_before = round(otp_before / signin_before * 100, 1) if signin_before else 0
    cr_after  = round(otp_after  / signin_after  * 100, 1) if signin_after  else 0

    # ── Assemble & write ─────────────────────────────────────────────
    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period": {
            "after_start":  LAUNCH_DATE,
            "after_end":    end,
            "after_days":   adays,
            "before_start": BEFORE_START,
            "before_end":   BEFORE_END,
            "before_days":  BEFORE_DAYS,
            "bug_fix_date": BUG_FIX_DATE,
        },
        "setup": {
            "screen_views":    screen_views,
            "enrolled":        enrolled,
            "deferred":        deferred,
            "failed":          enroll_failed,
            "enrollment_rate": enrollment_rate,
        },
        "login": {
            "clicked":      clicked,
            "verified":     verified,
            "os_failed":    os_failed,
            "bk_failed":    bk_failed,
            "fallback":     fallback,
            "success_rate": success_rate,
        },
        "platform": platform,
        "before_after": {
            "signin_before":        signin_before,
            "signin_after":         signin_after,
            "otp_before":           otp_before,
            "otp_after":            otp_after,
            "signup_before":        signup_before,
            "signup_after":         signup_after,
            "otp_cr_before":        cr_before,
            "otp_cr_after":         cr_after,
            "signin_per_day_before": round(signin_before / BEFORE_DAYS),
            "signin_per_day_after":  round(signin_after  / adays),
            "signup_per_day_before": round(signup_before / BEFORE_DAYS),
            "signup_per_day_after":  round(signup_after  / adays),
        },
        "daily": {
            "dates":              list(dates),
            "enrolled":           d_enrolled,
            "logins":             d_logins,
            "otp":                d_otp,
            "signups":            d_signups,
            "ios_fail_rate":      fail_rate(ios_fails,  ios_clicks),
            "android_fail_rate":  fail_rate(and_fails,  and_clicks),
            "ios_os_failed":      ios_fails,
            "android_os_failed":  and_fails,
            "ios_login_clicks":   ios_clicks,
            "android_login_clicks": and_clicks,
        },
    }

    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "biometrics_data.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)

    print(f"\nDone → {out_path}")
    print(f"  Enrolled:          {enrolled:,} ({enrollment_rate}%)")
    print(f"  Login success:     {verified:,}/{clicked:,} ({success_rate}%)")
    print(f"  iOS login success: {platform['iOS']['login_success_rate']}%  "
          f"(fail {platform['iOS']['os_fail_rate']}%)")
    print(f"  Android success:   {platform['Android']['login_success_rate']}%  "
          f"(fail {platform['Android']['os_fail_rate']}%)")


if __name__ == "__main__":
    main()
