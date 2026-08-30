"use client";

import Link from "next/link";

/**
 * Mints the session id in the browser at click time.
 *
 * Generating it during render would bake one id into the statically prerendered
 * home page, so every visitor would land in the same room.
 */
export default function StartInterviewButton() {
  return (
    <Link className="primary-action" href="/setup">Start a voice session</Link>
  );
}
