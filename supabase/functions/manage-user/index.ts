import { createClient } from "https://esm.sh/@supabase/supabase-js@2.53.0";

type ManagedRole = "org_admin" | "site_admin" | "site_operator";
type ManageAction = "update_role" | "remove_membership" | "delete_user";

type ManageUserRequest = {
  action?: ManageAction;
  membership_id?: string;
  user_id?: string;
  role?: ManagedRole;
  reason?: string;
};

type MembershipRow = {
  id: string;
  organization_id: string;
  site_id: string | null;
  user_id: string;
  role: string;
};

type Permission = {
  systemAdmin: boolean;
  orgAdmin: boolean;
  siteAdmin: boolean;
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

  let body: ManageUserRequest;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: "Invalid JSON body" }, 400);
  }

  try {
    if (body.action === "update_role") {
      return await updateRole(admin, caller.id, body);
    }
    if (body.action === "remove_membership") {
      return await removeMembership(admin, caller.id, body);
    }
    if (body.action === "delete_user") {
      return await deleteUserAccount(admin, caller.id, body);
    }
  } catch (error) {
    return jsonResponse({ error: errorMessage(error) }, 400);
  }

  return jsonResponse({ error: "Invalid action" }, 400);
});

async function updateRole(admin: ReturnType<typeof createClient>, callerUserId: string, body: ManageUserRequest) {
  const membershipId = String(body.membership_id ?? "").trim();
  const role = body.role;
  if (!membershipId || !isManagedRole(role)) {
    return jsonResponse({ error: "membership_id and a valid role are required" }, 400);
  }

  const membership = await getMembership(admin, membershipId);
  if (!membership) {
    return jsonResponse({ error: "Membership not found" }, 404);
  }
  if (membership.user_id === callerUserId) {
    return jsonResponse({ error: "You cannot change your own role" }, 400);
  }

  const permission = await resolvePermission(admin, callerUserId, membership.organization_id, membership.site_id);
  if (!canManageMembership(permission, membership, role)) {
    return jsonResponse({ error: "Not allowed to change this user role" }, 403);
  }
  if (!roleFitsScope(role, membership.site_id)) {
    return jsonResponse({ error: "Role does not match membership scope" }, 400);
  }

  const { error } = await admin.from("memberships").update({ role }).eq("id", membership.id);
  if (error) {
    return jsonResponse({ error: error.message }, 400);
  }

  await writeAudit(admin, {
    organizationId: membership.organization_id,
    actorUserId: callerUserId,
    action: "user_role_changed",
    membershipId: membership.id,
    metadata: {
      target_user_id: membership.user_id,
      previous_role: membership.role,
      next_role: role,
      site_id: membership.site_id,
    },
  });

  return jsonResponse({ ok: true, membership_id: membership.id, role });
}

async function removeMembership(admin: ReturnType<typeof createClient>, callerUserId: string, body: ManageUserRequest) {
  const membershipId = String(body.membership_id ?? "").trim();
  if (!membershipId) {
    return jsonResponse({ error: "membership_id is required" }, 400);
  }

  const membership = await getMembership(admin, membershipId);
  if (!membership) {
    return jsonResponse({ error: "Membership not found" }, 404);
  }
  if (membership.user_id === callerUserId) {
    return jsonResponse({ error: "You cannot remove your own access" }, 400);
  }

  const permission = await resolvePermission(admin, callerUserId, membership.organization_id, membership.site_id);
  if (!canManageMembership(permission, membership, null)) {
    return jsonResponse({ error: "Not allowed to remove this user access" }, 403);
  }

  const { error } = await admin.from("memberships").delete().eq("id", membership.id);
  if (error) {
    return jsonResponse({ error: error.message }, 400);
  }

  await writeAudit(admin, {
    organizationId: membership.organization_id,
    actorUserId: callerUserId,
    action: "user_membership_removed",
    membershipId: membership.id,
    metadata: {
      target_user_id: membership.user_id,
      role: membership.role,
      site_id: membership.site_id,
      reason: String(body.reason ?? "").trim(),
    },
  });

  return jsonResponse({ ok: true, membership_id: membership.id });
}

async function deleteUserAccount(admin: ReturnType<typeof createClient>, callerUserId: string, body: ManageUserRequest) {
  const userId = String(body.user_id ?? "").trim();
  if (!userId) {
    return jsonResponse({ error: "user_id is required" }, 400);
  }
  if (userId === callerUserId) {
    return jsonResponse({ error: "You cannot delete your own account" }, 400);
  }

  const permission = await resolvePermission(admin, callerUserId, "", null);
  if (!permission.systemAdmin) {
    return jsonResponse({ error: "Only system_admin can delete user accounts" }, 403);
  }

  const { data: userData } = await admin.auth.admin.getUserById(userId);
  const userEmail = userData.user?.email ?? "";

  const { data: memberships, error: membershipError } = await admin
    .from("memberships")
    .select("id, organization_id, site_id, user_id, role")
    .eq("user_id", userId);
  if (membershipError) {
    return jsonResponse({ error: membershipError.message }, 400);
  }

  const membershipRows = (memberships ?? []) as MembershipRow[];
  for (const membership of membershipRows) {
    await writeAudit(admin, {
      organizationId: membership.organization_id,
      actorUserId: callerUserId,
      action: "user_account_deleted",
      membershipId: membership.id,
      metadata: {
        target_user_id: userId,
        target_email: userEmail,
        role: membership.role,
        site_id: membership.site_id,
        reason: String(body.reason ?? "").trim(),
      },
    });
  }

  const { error: deleteMembershipError } = await admin.from("memberships").delete().eq("user_id", userId);
  if (deleteMembershipError) {
    return jsonResponse({ error: deleteMembershipError.message }, 400);
  }

  await admin.from("profiles").delete().eq("id", userId);

  const { error: deleteError } = await admin.auth.admin.deleteUser(userId, true);
  if (deleteError) {
    return jsonResponse({ error: deleteError.message }, 400);
  }

  return jsonResponse({ ok: true, user_id: userId });
}

async function getMembership(admin: ReturnType<typeof createClient>, membershipId: string) {
  const { data, error } = await admin
    .from("memberships")
    .select("id, organization_id, site_id, user_id, role")
    .eq("id", membershipId)
    .maybeSingle();
  if (error) {
    throw error;
  }
  return (data ?? null) as MembershipRow | null;
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

  if (!organizationId) {
    return { systemAdmin: false, orgAdmin: false, siteAdmin: false };
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

function canManageMembership(permission: Permission, membership: MembershipRow, nextRole: ManagedRole | null) {
  if (permission.systemAdmin) {
    return true;
  }
  if (!isManagedRole(membership.role)) {
    return false;
  }
  if (permission.orgAdmin) {
    return nextRole ? roleFitsScope(nextRole, membership.site_id) : true;
  }
  if (permission.siteAdmin) {
    return Boolean(membership.site_id) && isSiteRole(membership.role) && (!nextRole || isSiteRole(nextRole));
  }
  return false;
}

function isManagedRole(role: unknown): role is ManagedRole {
  return role === "org_admin" || role === "site_admin" || role === "site_operator";
}

function isSiteRole(role: unknown) {
  return role === "site_admin" || role === "site_operator";
}

function roleFitsScope(role: ManagedRole, siteId: string | null) {
  return siteId ? isSiteRole(role) : role === "org_admin";
}

async function writeAudit(
  admin: ReturnType<typeof createClient>,
  options: {
    organizationId: string | null;
    actorUserId: string;
    action: string;
    membershipId: string | null;
    metadata: Record<string, unknown>;
  },
) {
  await admin.from("audit_log").insert({
    organization_id: options.organizationId,
    actor_user_id: options.actorUserId,
    action: options.action,
    resource_type: "membership",
    resource_id: options.membershipId,
    metadata: options.metadata,
  });
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

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "User management request failed";
}
