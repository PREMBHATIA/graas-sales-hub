/**
 * Graas click redirector — Cloudflare Worker.
 *
 * Replaces the Apps Script web app as the CLICK hop. Apps Script physically
 * cannot do this job: it serves HTML inside an iframe sandboxed with
 * `allow-top-navigation-by-user-activation`, so its on-load redirect is
 * blocked and the visitor is stranded on script.google.com. A Worker returns
 * a real 302, so the browser moves immediately — nothing to block.
 *
 * Logging is unchanged: this fires the SAME Apps Script endpoint that already
 * writes the Tracking tab, so tracking_ids, the sheet, and every chart in
 * SalesHub Analytics keep working exactly as they do today. Apps Script is
 * perfectly good at logging — it was only bad at redirecting.
 *
 * Deploy (no DNS needed for v1):
 *   1. dash.cloudflare.com → Workers & Pages → Create → paste this
 *   2. Settings → Variables → LOG_URL = the existing PIXEL_BASE_URL .../exec
 *   3. Deploy → copy the https://<name>.<account>.workers.dev URL
 *   4. In Streamlit secrets: CLICK_BASE_URL=<that url>  and  CLICK_TRACKING=1
 *
 * Later, to put it on graas.ai (nicer in an inbox, better deliverability):
 *   Workers → Triggers → Custom domain → click.graas.ai, then update
 *   CLICK_BASE_URL. One DNS record; no code change.
 */

export default {
  async fetch(request, env, ctx) {
    const src = new URL(request.url);
    const dest = src.searchParams.get("u");
    const tid = src.searchParams.get("t") || "";

    // No destination → send them somewhere real rather than showing an error.
    if (!dest) return Response.redirect("https://graas.ai", 302);

    // Only ever redirect to http(s). Without this the ?u= param is an open
    // redirect that will happily emit javascript: or data: URLs — a phishing
    // gadget hosted on our own domain, and a deliverability problem.
    let target;
    try {
      target = new URL(dest);
      if (target.protocol !== "https:" && target.protocol !== "http:") {
        return Response.redirect("https://graas.ai", 302);
      }
    } catch {
      return Response.redirect("https://graas.ai", 302);
    }

    // Log without making the visitor wait: waitUntil lets the redirect return
    // immediately while this finishes in the background. A logging failure
    // must never cost us the click, hence the swallowed catch.
    if (tid && env.LOG_URL) {
      const log = `${env.LOG_URL}?t=${encodeURIComponent(tid)}&e=click&u=${encodeURIComponent(dest)}`;
      ctx.waitUntil(fetch(log, { method: "GET" }).catch(() => {}));
    }

    return Response.redirect(target.toString(), 302);
  },
};
