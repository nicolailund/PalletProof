import { createClient } from "https://esm.sh/@supabase/supabase-js@2.53.0";

type InviteRole = "org_admin" | "site_admin" | "site_operator";

type InviteRequest = {
  email?: string;
  full_name?: string;
  organization_id?: string;
  site_id?: string | null;
  role?: InviteRole;
};

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }
  if (request.method !== "POST") {
    return jsonResponse({ error: "Method not allowed" }, 405);
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  const portalUrl = Deno.env.get("PUBLIC_PORTAL_URL") ?? Deno.env.get("SITE_URL") ?? "";
  if (!supabaseUrl || !serviceRoleKey) {
    return jsonResponse({ error: "Function is missing Supabase service configuration" }, 500);
  }

  const authorization = request.headers.get("authorization") ?? "";
  const jwt = authorization.replace(/^Bearer\s+/i, "");
  if (!jwt) {
    return jsonResponse({ error: "Missing authorization" }, 401);
  }

  const admin = createClient(supabaseUrl, serviceRoleKey, {
    auth: {
      autoRefreshToken: false,
      persistSession: false,
    },
  });

  const { data: callerData, error: callerError } = await admin.auth.getUser(jwt);
  const caller = callerData.user;
  if (callerError || !caller) {
    return jsonResponse({ error: "Invalid authorization" }, 401);
  }

  let body: InviteRequest;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: "Invalid JSON body" }, 400);
  }

  const email = normalizeEmail(body.email);
  const fullName = String(body.full_name ?? "").trim();
  const organizationId = String(body.organization_id ?? "").trim();
  const siteId = body.site_id ? String(body.site_id).trim() : null;
  const role = body.role;

  if (!email || !organizationId || !role) {
    return jsonResponse({ error: "email, organization_id and role are required" }, 400);
  }
  if (!["org_admin", "site_admin", "site_operator"].includes(role)) {
    return jsonResponse({ error: "Invalid role" }, 400);
  }
  if (role === "org_admin" && siteId) {
    return jsonResponse({ error: "org_admin must be organization-scoped" }, 400);
  }
  if ((role === "site_admin" || role === "site_operator") && !siteId) {
    return jsonResponse({ error: "site role requires site_id" }, 400);
  }

  const permission = await resolvePermission(admin, caller.id, organizationId, siteId);
  if (!canInvite(permission, role, siteId)) {
    return jsonResponse({ error: "Not allowed to invite this user or role" }, 403);
  }

  const { data: invited, error: inviteError } = await admin.auth.admin.inviteUserByEmail(email, {
    data: { full_name: fullName },
    redirectTo: portalUrl || undefined,
  });
  if (inviteError || !invited.user) {
    return jsonResponse({ error: inviteError?.message ?? "Could not invite user" }, 400);
  }

  const invitedUserId = invited.user.id;
  const { error: profileError } = await admin
    .from("profiles")
    .upsert({ id: invitedUserId, full_name: fullName }, { onConflict: "id" });
  if (profileError) {
    return jsonResponse({ error: profileError.message }, 400);
  }

  const existingQuery = admin
    .from("memberships")
    .select("id")
    .eq("organization_id", organizationId)
    .eq("user_id", invitedUserId)
    .limit(1);
  const scopedExistingQuery = siteId === null ? existingQuery.is("site_id", null) : existingQuery.eq("site_id", siteId);
  const { data: existingMemberships, error: existingError } = await scopedExistingQuery;
  if (existingError) {
    return jsonResponse({ error: existingError.message }, 400);
  }

  const membershipPayload = {
    organization_id: organizationId,
    site_id: siteId,
    user_id: invitedUserId,
    role,
  };

  let membershipId = existingMemberships?.[0]?.id as string | undefined;
  if (membershipId) {
    const { error: updateError } = await admin.from("memberships").update({ role }).eq("id", membershipId);
    if (updateError) {
      return jsonResponse({ error: updateError.message }, 400);
    }
  } else {
    const { data: insertedMembership, error: insertError } = await admin
      .from("memberships")
      .insert(membershipPayload)
      .select("id")
      .single();
    if (insertError) {
      return jsonResponse({ error: insertError.message }, 400);
    }
    membershipId = insertedMembership.id;
  }

  await admin.from("audit_log").insert({
    organization_id: organizationId,
    actor_user_id: caller.id,
    action: "user_invited",
    resource_type: "membership",
    resource_id: membershipId,
    metadata: {
      email,
      role,
      site_id: siteId,
      invited_user_id: invitedUserId,
    },
  });

  return jsonResponse({
    ok: true,
    user_id: invitedUserId,
    membership_id: membershipId,
  });
});

function normalizeEmail(value: unknown) {
  const email = String(value ?? "").trim().toLowerCase();
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ? email : "";
}

async function resolvePermission(
  admin: ReturnType<typeof createClient>,
  callerUserId: string,
  organizationId: string,
  siteId: string | null,
) {
  const { data: systemAdminRows } = await admin.from("platform_admins").select("user_id").eq("user_id", callerUserId).limit(1);
  if ((systemAdminRows ?? []).length > 0) {
    return { systemAdmin: true, orgAdmin: true, siteAdmin: true };
  }

  const { data: orgAdminRows } = await admin
    .from("memberships")
    .select("id")
    .eq("organization_id", organizationId)
    .eq("user_id", callerUserId)
    .is("site_id", null)
    .in("role", ["owner", "admin", "org_admin"])
    .limit(1);
  if ((orgAdminRows ?? []).length > 0) {
    return { systemAdmin: false, orgAdmin: true, siteAdmin: false };
  }

  if (!siteId) {
    return { systemAdmin: false, orgAdmin: false, siteAdmin: false };
  }

  const { data: siteAdminRows } = await admin
    .from("memberships")
    .select("id")
    .eq("organization_id", organizationId)
    .eq("site_id", siteId)
    .eq("user_id", callerUserId)
    .eq("role", "site_admin")
    .limit(1);
  return {
    systemAdmin: false,
    orgAdmin: false,
    siteAdmin: (siteAdminRows ?? []).length > 0,
  };
}

function canInvite(
  permission: { systemAdmin: boolean; orgAdmin: boolean; siteAdmin: boolean },
  role: InviteRole,
  siteId: string | null,
) {
  if (permission.systemAdmin) return true;
  if (permission.orgAdmin) return true;
  if (permission.siteAdmin) return Boolean(siteId) && (role === "site_admin" || role === "site_operator");
  return false;
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      ...corsHeaders,
      "content-type": "application/json; charset=utf-8",
    },
  });
}
