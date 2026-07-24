import { FormEvent, useEffect, useMemo, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import QRCode from "qrcode";
import {
  Activity,
  Boxes,
  Check,
  Copy,
  CreditCard,
  Database,
  Download,
  Eye,
  EyeOff,
  ExternalLink,
  Film,
  HardDrive,
  KeyRound,
  LogOut,
  Moon,
  Plus,
  QrCode,
  RefreshCcw,
  Search,
  Share2,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UploadCloud,
  Wifi,
  Zap,
} from "lucide-react";
import { isSupabaseConfigured, requireSupabase, supabaseUrl } from "./supabase";
import type {
  BillingPrice,
  CurrentMembershipRow,
  Device,
  DeviceEvent,
  Membership,
  Organization,
  Site,
  SiteBillingUsage,
  SoftwareRollout,
  Video,
} from "./types";

type Tab = "overview" | "devices" | "videos" | "billing" | "updates";

type DeviceForm = {
  serialNumber: string;
  displayName: string;
  siteId: string;
};

type ProvisionForm = {
  wifiSsid: string;
  wifiPassword: string;
  expiresDays: number;
};

type RolloutForm = {
  updateId: string;
  policy: "force" | "night";
  version: string;
  targetRef: string;
  targetCommit: string;
  description: string;
};

type SiteEntitlementForm = {
  includedStorageGb: string;
  extraStorageGb: string;
  retentionDays: string;
  autoDeleteEnabled: boolean;
  protectSharedVideos: boolean;
};

type PriceForm = {
  unitAmount: string;
};

type ShareResult = {
  url: string;
  token: string;
};

type VideoPlayerState = {
  video: Video;
  playbackUrl: string;
  downloadUrl: string;
  loading: boolean;
  error: string;
};

const emptyDeviceForm: DeviceForm = {
  serialNumber: "",
  displayName: "",
  siteId: "",
};

const emptyProvisionForm: ProvisionForm = {
  wifiSsid: "",
  wifiPassword: "",
  expiresDays: 7,
};

const emptyRolloutForm: RolloutForm = {
  updateId: "",
  policy: "night",
  version: "0.1.0",
  targetRef: "main",
  targetCommit: "",
  description: "",
};

const emptySiteEntitlementForm: SiteEntitlementForm = {
  includedStorageGb: "100",
  extraStorageGb: "0",
  retentionDays: "90",
  autoDeleteEnabled: true,
  protectSharedVideos: true,
};

const emptyPriceForm: PriceForm = {
  unitAmount: "0",
};

const statusLabel: Record<Device["status"], string> = {
  unprovisioned: "Ikke provisioneret",
  online: "Online",
  offline: "Offline",
  recording: "Optager",
  error: "Fejl",
  disabled: "Deaktiveret",
};

const statusClass: Record<Device["status"], string> = {
  unprovisioned: "neutral",
  online: "success",
  offline: "neutral",
  recording: "active",
  error: "danger",
  disabled: "neutral",
};

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("overview");
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [videos, setVideos] = useState<Video[]>([]);
  const [events, setEvents] = useState<DeviceEvent[]>([]);
  const [rollouts, setRollouts] = useState<SoftwareRollout[]>([]);
  const [billingPrices, setBillingPrices] = useState<BillingPrice[]>([]);
  const [billingUsage, setBillingUsage] = useState<SiteBillingUsage[]>([]);
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false);
  const [selectedOrgId, setSelectedOrgId] = useState("");
  const [selectedSiteId, setSelectedSiteId] = useState("all");
  const [deviceForm, setDeviceForm] = useState<DeviceForm>(emptyDeviceForm);
  const [provisionDevice, setProvisionDevice] = useState<Device | null>(null);
  const [provisionForm, setProvisionForm] = useState<ProvisionForm>(emptyProvisionForm);
  const [deleteDevice, setDeleteDevice] = useState<Device | null>(null);
  const [resetDevice, setResetDevice] = useState<Device | null>(null);
  const [editingEntitlement, setEditingEntitlement] = useState<SiteBillingUsage | null>(null);
  const [siteEntitlementForm, setSiteEntitlementForm] = useState<SiteEntitlementForm>(emptySiteEntitlementForm);
  const [editingPrice, setEditingPrice] = useState<BillingPrice | null>(null);
  const [priceForm, setPriceForm] = useState<PriceForm>(emptyPriceForm);
  const [qrValue, setQrValue] = useState("");
  const [qrImage, setQrImage] = useState("");
  const [resetQrValue, setResetQrValue] = useState("");
  const [resetQrImage, setResetQrImage] = useState("");
  const [rolloutForm, setRolloutForm] = useState<RolloutForm>(emptyRolloutForm);
  const [shareResult, setShareResult] = useState<ShareResult | null>(null);
  const [videoPlayer, setVideoPlayer] = useState<VideoPlayerState | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (!isSupabaseConfigured) {
      setAuthLoading(false);
      return;
    }

    const client = requireSupabase();
    client.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setAuthLoading(false);
    });

    const {
      data: { subscription },
    } = client.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
    });

    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (session) {
      void loadWorkspace();
    }
  }, [session]);

  const organizations = useMemo(() => {
    const byId = new Map<string, Organization>();
    for (const membership of memberships) {
      const organization = firstRelation(membership.organizations);
      if (organization) {
        byId.set(organization.id, organization);
      }
    }
    return Array.from(byId.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [memberships]);

  const selectedOrganization = organizations.find((organization) => organization.id === selectedOrgId) ?? organizations[0];
  const selectedSite = selectedSiteId === "all" ? null : sites.find((site) => site.id === selectedSiteId) ?? null;
  const canManageBilling = memberships.some(
    (membership) =>
      membership.organization_id === selectedOrganization?.id &&
      membership.site_id === null &&
      (membership.role === "owner" || membership.role === "admin"),
  );
  const recentEvents = events.slice(0, 8);
  const visibleVideos = videos.filter((video) => {
    const needle = search.trim().toLowerCase();
    if (!needle) {
      return true;
    }
    return `${video.scanned_id} ${video.filename} ${video.device_serial_number} ${videoDeviceLabel(video)}`
      .toLowerCase()
      .includes(needle);
  });

  const stats = useMemo(() => {
    const online = devices.filter((device) => device.status === "online" || device.status === "recording").length;
    const recording = devices.filter((device) => device.status === "recording").length;
    const unprovisioned = devices.filter((device) => device.status === "unprovisioned").length;
    const failedVideos = videos.filter((video) => video.status === "failed").length;
    return { online, recording, unprovisioned, failedVideos };
  }, [devices, videos]);

  async function loadWorkspace(nextOrgId = selectedOrgId, nextSiteId = selectedSiteId) {
    const client = requireSupabase();
    setLoading(true);
    setError("");

    try {
      if (session) {
        const { data: platformAdminData } = await client
          .from("platform_admins")
          .select("user_id")
          .eq("user_id", session.user.id)
          .maybeSingle();
        setIsPlatformAdmin(Boolean(platformAdminData));
      }

      const { data: membershipData, error: membershipError } = await client.rpc("current_memberships");

      if (membershipError) {
        throw membershipError;
      }

      const nextMemberships = currentMembershipRowsToMemberships((membershipData ?? []) as CurrentMembershipRow[]);
      setMemberships(nextMemberships);

      const orgList = uniqueOrganizations(nextMemberships);
      const effectiveOrgId = orgList.some((organization) => organization.id === nextOrgId) ? nextOrgId : orgList[0]?.id ?? "";
      setSelectedOrgId(effectiveOrgId);

      if (!effectiveOrgId) {
        setSites([]);
        setDevices([]);
        setVideos([]);
        setEvents([]);
        setRollouts([]);
        setBillingPrices([]);
        setBillingUsage([]);
        return;
      }

      const { data: siteData, error: siteError } = await client
        .from("sites")
        .select("*")
        .eq("organization_id", effectiveOrgId)
        .order("name", { ascending: true });

      if (siteError) {
        throw siteError;
      }

      const nextSites = (siteData ?? []) as Site[];
      setSites(nextSites);

      const effectiveSiteId = nextSiteId !== "all" && nextSites.some((site) => site.id === nextSiteId) ? nextSiteId : "all";
      setSelectedSiteId(effectiveSiteId);
      setDeviceForm((current) => ({
        ...current,
        siteId: current.siteId || nextSites[0]?.id || "",
      }));

      let deviceQuery = client.from("devices").select("*").eq("organization_id", effectiveOrgId).order("created_at", {
        ascending: false,
      });
      let videoQuery = client
        .from("videos")
        .select("*, devices(serial_number, display_name), sites!videos_site_id_fkey(name)")
        .eq("organization_id", effectiveOrgId)
        .order("created_at", { ascending: false })
        .limit(100);
      let eventQuery = client
        .from("device_events")
        .select("*, devices(serial_number, display_name)")
        .eq("organization_id", effectiveOrgId)
        .order("created_at", { ascending: false })
        .limit(50);
      const priceQuery = client
        .from("billing_price_catalog")
        .select("*")
        .eq("active", true)
        .order("sort_order", { ascending: true });

      if (effectiveSiteId !== "all") {
        deviceQuery = deviceQuery.eq("site_id", effectiveSiteId);
        videoQuery = videoQuery.eq("site_id", effectiveSiteId);
        eventQuery = eventQuery.eq("site_id", effectiveSiteId);
      }

      const [deviceResult, videoResult, eventResult, rolloutResult, priceResult, usageResult] = await Promise.all([
        deviceQuery,
        videoQuery,
        eventQuery,
        client.from("software_rollouts").select("*").order("created_at", { ascending: false }).limit(20),
        priceQuery,
        client.rpc("billing_site_usage", { p_organization_id: effectiveOrgId }),
      ]);

      if (deviceResult.error) throw deviceResult.error;
      if (videoResult.error) throw videoResult.error;
      if (eventResult.error) throw eventResult.error;
      if (rolloutResult.error) throw rolloutResult.error;
      if (priceResult.error) throw priceResult.error;
      if (usageResult.error) throw usageResult.error;

      setDevices((deviceResult.data ?? []) as Device[]);
      setVideos((videoResult.data ?? []) as Video[]);
      setEvents((eventResult.data ?? []) as DeviceEvent[]);
      setRollouts((rolloutResult.data ?? []) as SoftwareRollout[]);
      setBillingPrices((priceResult.data ?? []) as BillingPrice[]);
      setBillingUsage((usageResult.data ?? []) as SiteBillingUsage[]);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  async function handleLogin(event: FormEvent) {
    event.preventDefault();
    const client = requireSupabase();
    setLoginError("");
    const { error: authError } = await client.auth.signInWithPassword({ email, password });
    if (authError) {
      setLoginError(authError.message);
    }
  }

  async function handleLogout() {
    await requireSupabase().auth.signOut();
    setSession(null);
    setMemberships([]);
    setSites([]);
    setDevices([]);
    setVideos([]);
    setBillingPrices([]);
    setBillingUsage([]);
    setIsPlatformAdmin(false);
  }

  async function handleAddDevice(event: FormEvent) {
    event.preventDefault();
    if (!selectedOrganization) return;

    const serialNumber = deviceForm.serialNumber.trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(serialNumber)) {
      setError("Serienummer må kun indeholde bogstaver, tal, punktum, underscore og bindestreg.");
      return;
    }

    const siteId = deviceForm.siteId || sites[0]?.id;
    if (!siteId) {
      setError("Opret et site før du opretter en enhed.");
      return;
    }

    const client = requireSupabase();
    setError("");
    const { data: insertedDevice, error: insertError } = await client.from("devices").insert({
      organization_id: selectedOrganization.id,
      site_id: siteId,
      serial_number: serialNumber,
      display_name: deviceForm.displayName.trim(),
      status: "unprovisioned",
    }).select("*").single();

    if (insertError) {
      setError(insertError.message);
      return;
    }

    setDeviceForm({ ...emptyDeviceForm, siteId });
    setNotice(`Enhed ${serialNumber} er oprettet.`);
    if (insertedDevice) {
      setDevices((current) => [insertedDevice as Device, ...current]);
    }
    await loadWorkspace();
  }

  async function handleGenerateProvisioningQr(event: FormEvent) {
    event.preventDefault();
    if (!provisionDevice || !selectedOrganization || !session) return;

    const site = sites.find((candidate) => candidate.id === provisionDevice.site_id);
    if (!site) {
      setError("Enheden mangler et gyldigt site.");
      return;
    }

    try {
      const activationToken = randomToken(32);
      const tokenHash = await sha256Hex(activationToken);
      const expiresAt = new Date(Date.now() + provisionForm.expiresDays * 24 * 60 * 60 * 1000).toISOString();
      const client = requireSupabase();

      const { error: tokenError } = await client.from("device_activation_tokens").insert({
        device_id: provisionDevice.id,
        token_hash: tokenHash,
        expires_at: expiresAt,
        created_by: session.user.id,
      });

      if (tokenError) {
        throw tokenError;
      }

      const payload = {
        type: "palletproof_provisioning",
        version: 1,
        serial_number: provisionDevice.serial_number,
        customer_id: safeIdentifier(selectedOrganization.slug),
        site_id: safeIdentifier(site.slug),
        activation_token: activationToken,
        wifi: {
          ssid: provisionForm.wifiSsid,
          password: provisionForm.wifiPassword,
        },
        api_base_url: supabaseUrl ?? "",
        expires_at: expiresAt,
      };

      const qrText = `PALLETPROOF1.${base64UrlJson(payload)}`;
      const qrDataUrl = await QRCode.toDataURL(qrText, {
        width: 340,
        margin: 2,
        errorCorrectionLevel: "M",
      });

      setQrValue(qrText);
      setQrImage(qrDataUrl);
      setNotice(`Provisioning-QR klar for ${provisionDevice.serial_number}.`);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function handleCreateRollout(event: FormEvent) {
    event.preventDefault();
    const client = requireSupabase();
    const updateId = rolloutForm.updateId.trim();
    if (!updateId) {
      setError("Update ID er påkrævet.");
      return;
    }

    const { error: rolloutError } = await client.from("software_rollouts").insert({
      update_id: updateId,
      policy: rolloutForm.policy,
      target_ref: rolloutForm.targetRef.trim() || "main",
      target_commit: rolloutForm.targetCommit.trim(),
      version: rolloutForm.version.trim(),
      description: rolloutForm.description.trim(),
      enabled: true,
      created_by: session?.user.id,
    });

    if (rolloutError) {
      setError(rolloutError.message);
      return;
    }

    setRolloutForm(emptyRolloutForm);
    setNotice(`Rollout ${updateId} er oprettet.`);
    await loadWorkspace();
  }

  async function handlePrepareShare(video: Video) {
    if (!session) return;
    if (!videoPrivacyReady(video)) {
      setError("Videoen kan ikke deles, før privacy-processering er færdig.");
      return;
    }
    try {
      const token = randomToken(32);
      const tokenHash = await sha256Hex(token);
      const expiresAt = new Date(Date.now() + 14 * 24 * 60 * 60 * 1000).toISOString();
      const client = requireSupabase();
      const { error: shareError } = await client.from("video_shares").insert({
        video_id: video.id,
        token_hash: tokenHash,
        expires_at: expiresAt,
        created_by: session.user.id,
        allow_download: false,
      });
      if (shareError) {
        throw shareError;
      }
      setShareResult({
        token,
        url: `${window.location.origin}/share/${token}`,
      });
      setNotice(`Share-token oprettet for ${video.scanned_id}.`);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function handleOpenVideo(video: Video) {
    setVideoPlayer({ video, playbackUrl: "", downloadUrl: "", loading: true, error: "" });

    if (video.status !== "uploaded" || !videoPrivacyReady(video)) {
      setVideoPlayer({
        video,
        playbackUrl: "",
        downloadUrl: "",
        loading: false,
        error: video.status !== "uploaded" ? "Videoen er ikke klar til afspilning endnu." : "Videoen afventer privacy-processering.",
      });
      return;
    }

    try {
      const storage = requireSupabase().storage.from(video.storage_bucket || "videos");
      const [playbackResult, downloadResult] = await Promise.all([
        storage.createSignedUrl(video.storage_path, 60 * 60),
        storage.createSignedUrl(video.storage_path, 60 * 60, { download: video.filename || true }),
      ]);

      if (playbackResult.error || !playbackResult.data?.signedUrl) {
        throw playbackResult.error ?? new Error("Kunne ikke oprette afspilningslink.");
      }
      if (downloadResult.error || !downloadResult.data?.signedUrl) {
        throw downloadResult.error ?? new Error("Kunne ikke oprette downloadlink.");
      }

      setVideoPlayer({
        video,
        playbackUrl: playbackResult.data.signedUrl,
        downloadUrl: downloadResult.data.signedUrl,
        loading: false,
        error: "",
      });
    } catch (caught) {
      setVideoPlayer((current) =>
        current?.video.id === video.id
          ? {
              ...current,
              loading: false,
              error: `Videoen kunne ikke åbnes: ${errorMessage(caught)}`,
            }
          : current,
      );
    }
  }

  async function handleDeleteDevice(device: Device) {
    const label = device.display_name || device.serial_number;
    try {
      const client = requireSupabase();
      const { error: deleteError } = await client.from("devices").delete().eq("id", device.id);
      if (deleteError) {
        throw deleteError;
      }
      setDevices((current) => current.filter((candidate) => candidate.id !== device.id));
      setDeleteDevice(null);
      setNotice(`Enhed ${label} er slettet.`);
      await loadWorkspace();
    } catch (caught) {
      setError(`Enheden kunne ikke slettes: ${errorMessage(caught)}`);
    }
  }

  function openEditEntitlement(usage: SiteBillingUsage) {
    setEditingEntitlement(usage);
    setSiteEntitlementForm({
      includedStorageGb: String(usage.included_storage_gb),
      extraStorageGb: String(usage.extra_storage_gb),
      retentionDays: String(usage.retention_days),
      autoDeleteEnabled: usage.auto_delete_enabled,
      protectSharedVideos: usage.protect_shared_videos,
    });
    setError("");
  }

  async function handleSaveSiteEntitlement(event: FormEvent) {
    event.preventDefault();
    if (!editingEntitlement || !canManageBilling) return;

    const includedStorageGb = Number(siteEntitlementForm.includedStorageGb);
    const extraStorageGb = Number(siteEntitlementForm.extraStorageGb);
    const retentionDays = Number(siteEntitlementForm.retentionDays);

    if (!Number.isFinite(includedStorageGb) || includedStorageGb < 0) {
      setError("Inkluderet storage skal være 0 GB eller mere.");
      return;
    }
    if (!Number.isFinite(extraStorageGb) || extraStorageGb < 0) {
      setError("Ekstra storage skal være 0 GB eller mere.");
      return;
    }
    if (!Number.isInteger(retentionDays) || retentionDays < 1) {
      setError("Retention skal være mindst 1 dag.");
      return;
    }

    const client = requireSupabase();
    const { error: entitlementError } = await client.from("site_billing_entitlements").upsert({
      organization_id: editingEntitlement.organization_id,
      site_id: editingEntitlement.site_id,
      included_storage_gb: includedStorageGb,
      extra_storage_gb: extraStorageGb,
      retention_days: retentionDays,
      auto_delete_enabled: siteEntitlementForm.autoDeleteEnabled,
      protect_shared_videos: siteEntitlementForm.protectSharedVideos,
      site_service_price_code: "site_service_base",
      storage_addon_price_code: "storage_extra_gb_monthly",
    });

    if (entitlementError) {
      setError(entitlementError.message);
      return;
    }

    setNotice(`Billing-regler opdateret for ${editingEntitlement.site_name}.`);
    setEditingEntitlement(null);
    await loadWorkspace();
  }

  function openEditPrice(price: BillingPrice) {
    setEditingPrice(price);
    setPriceForm({ unitAmount: String(minorAmount(price) / 100) });
    setError("");
  }

  async function handleSavePrice(event: FormEvent) {
    event.preventDefault();
    if (!editingPrice || !isPlatformAdmin) return;

    const unitAmount = Number(priceForm.unitAmount.replace(",", "."));
    if (!Number.isFinite(unitAmount) || unitAmount < 0) {
      setError("Prisen skal være 0 kr. eller mere.");
      return;
    }

    const { error: priceError } = await requireSupabase()
      .from("billing_price_catalog")
      .update({ unit_amount_minor: Math.round(unitAmount * 100) })
      .eq("id", editingPrice.id);

    if (priceError) {
      setError(priceError.message);
      return;
    }

    setNotice(`Pris opdateret: ${editingPrice.name}.`);
    setEditingPrice(null);
    await loadWorkspace();
  }

  function openProvisioning(device: Device) {
    setProvisionDevice(device);
    setProvisionForm(emptyProvisionForm);
    setQrValue("");
    setQrImage("");
    setError("");
  }

  async function openResetQr(device: Device) {
    try {
      const payload = {
        type: "palletproof_reset",
        version: 1,
        serial_number: device.serial_number,
      };
      const qrText = `PALLETPROOFRESET1.${base64UrlJson(payload)}`;
      const qrDataUrl = await QRCode.toDataURL(qrText, {
        width: 340,
        margin: 2,
        errorCorrectionLevel: "M",
      });
      setResetDevice(device);
      setResetQrValue(qrText);
      setResetQrImage(qrDataUrl);
      setNotice(`Reset-QR klar for ${device.serial_number}.`);
      setError("");
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  if (!isSupabaseConfigured) {
    return <MissingConfiguration />;
  }

  if (authLoading) {
    return <ShellState label="Indlæser session" />;
  }

  if (!session) {
    return (
      <main className="login-page">
        <section className="login-panel">
          <div className="brand-lockup">
            <div className="brand-mark">
              <PalletProofMark size={34} />
            </div>
            <div>
              <h1>PalletProof Admin</h1>
              <p>Driftsoverblik for palleoptagelser, enheder og provisioning.</p>
            </div>
          </div>
          <form onSubmit={handleLogin} className="login-form">
            <label>
              Email
              <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" />
            </label>
            <label>
              Password
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
              />
            </label>
            {loginError && <p className="form-error">{loginError}</p>}
            <button type="submit" className="primary-button">
              <KeyRound size={16} />
              Log ind
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup compact">
          <div className="brand-mark">
            <PalletProofMark size={32} />
          </div>
          <div>
            <strong>PalletProof</strong>
            <span>Admin</span>
          </div>
        </div>

        <nav className="nav-list" aria-label="Primær navigation">
          <NavButton active={tab === "overview"} icon={<Activity size={17} />} label="Overblik" onClick={() => setTab("overview")} />
          <NavButton active={tab === "devices"} icon={<QrCode size={17} />} label="Enheder" onClick={() => setTab("devices")} />
          <NavButton active={tab === "videos"} icon={<Film size={17} />} label="Videoer" onClick={() => setTab("videos")} />
          <NavButton active={tab === "billing"} icon={<CreditCard size={17} />} label="Billing" onClick={() => setTab("billing")} />
          <NavButton active={tab === "updates"} icon={<RefreshCcw size={17} />} label="Updates" onClick={() => setTab("updates")} />
        </nav>

        <button className="ghost-button logout" onClick={handleLogout}>
          <LogOut size={16} />
          Log ud
        </button>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">{selectedOrganization?.name ?? "Ingen organisation"}</p>
            <h1>{headingFor(tab)}</h1>
          </div>
          <div className="toolbar">
            <select value={selectedOrgId} onChange={(event) => void loadWorkspace(event.target.value, "all")}>
              {organizations.map((organization) => (
                <option key={organization.id} value={organization.id}>
                  {organization.name}
                </option>
              ))}
            </select>
            <select value={selectedSiteId} onChange={(event) => void loadWorkspace(selectedOrgId, event.target.value)}>
              <option value="all">Alle sites</option>
              {sites.map((site) => (
                <option key={site.id} value={site.id}>
                  {site.name}
                </option>
              ))}
            </select>
            <button className="icon-button" onClick={() => void loadWorkspace()} aria-label="Opdater data">
              <RefreshCcw size={17} />
            </button>
          </div>
        </header>

        {notice && (
          <button className="notice success" onClick={() => setNotice("")}>
            <Check size={16} />
            {notice}
          </button>
        )}
        {error && (
          <button className="notice danger" onClick={() => setError("")}>
            {error}
          </button>
        )}

        {loading && <div className="loading-line" />}

        {memberships.length === 0 ? (
          <EmptyState
            title="Ingen adgang endnu"
            text={`Logget ind som ${session.user.email ?? session.user.id}. User ID: ${session.user.id}`}
          />
        ) : (
          <>
            {tab === "overview" && (
              <Overview
                devices={devices}
                videos={videos}
                events={recentEvents}
                stats={stats}
                selectedSite={selectedSite}
                onOpenDevices={() => setTab("devices")}
              />
            )}

            {tab === "devices" && (
              <DevicesView
                devices={devices}
                sites={sites}
                deviceForm={deviceForm}
                setDeviceForm={setDeviceForm}
                onAddDevice={handleAddDevice}
                onProvision={openProvisioning}
                onResetQr={(device) => void openResetQr(device)}
                onDeleteDevice={(device) => {
                  setDeleteDevice(device);
                  setError("");
                }}
              />
            )}

            {tab === "videos" && (
              <VideosView
                videos={visibleVideos}
                search={search}
                setSearch={setSearch}
                onOpenVideo={handleOpenVideo}
                onShare={handlePrepareShare}
                shareResult={shareResult}
                clearShare={() => setShareResult(null)}
              />
            )}

            {tab === "billing" && (
              <BillingView
                prices={billingPrices}
                usage={selectedSite ? billingUsage.filter((row) => row.site_id === selectedSite.id) : billingUsage}
                canManageBilling={canManageBilling}
                isPlatformAdmin={isPlatformAdmin}
                onEditEntitlement={openEditEntitlement}
                onEditPrice={openEditPrice}
              />
            )}

            {tab === "updates" && (
              <UpdatesView
                rollouts={rollouts}
                rolloutForm={rolloutForm}
                setRolloutForm={setRolloutForm}
                onCreateRollout={handleCreateRollout}
              />
            )}
          </>
        )}
      </section>

      {provisionDevice && (
        <ProvisioningModal
          device={provisionDevice}
          form={provisionForm}
          setForm={setProvisionForm}
          qrImage={qrImage}
          qrValue={qrValue}
          onSubmit={handleGenerateProvisioningQr}
          onClose={() => setProvisionDevice(null)}
        />
      )}

      {deleteDevice && (
        <DeleteDeviceModal
          device={deleteDevice}
          onCancel={() => setDeleteDevice(null)}
          onConfirm={() => void handleDeleteDevice(deleteDevice)}
        />
      )}

      {resetDevice && (
        <ResetQrModal
          device={resetDevice}
          qrImage={resetQrImage}
          qrValue={resetQrValue}
          onClose={() => setResetDevice(null)}
        />
      )}

      {videoPlayer && <VideoPlayerModal state={videoPlayer} onClose={() => setVideoPlayer(null)} />}

      {editingEntitlement && (
        <SiteEntitlementModal
          usage={editingEntitlement}
          form={siteEntitlementForm}
          setForm={setSiteEntitlementForm}
          canManageBilling={canManageBilling}
          onSubmit={handleSaveSiteEntitlement}
          onClose={() => setEditingEntitlement(null)}
        />
      )}

      {editingPrice && (
        <PriceModal
          price={editingPrice}
          form={priceForm}
          setForm={setPriceForm}
          isPlatformAdmin={isPlatformAdmin}
          onSubmit={handleSavePrice}
          onClose={() => setEditingPrice(null)}
        />
      )}
    </main>
  );
}

function Overview({
  devices,
  videos,
  events,
  stats,
  selectedSite,
  onOpenDevices,
}: {
  devices: Device[];
  videos: Video[];
  events: DeviceEvent[];
  stats: { online: number; recording: number; unprovisioned: number; failedVideos: number };
  selectedSite: Site | null;
  onOpenDevices: () => void;
}) {
  return (
    <div className="content-grid">
      <section className="metrics-grid">
        <Metric icon={<Activity size={18} />} label="Online enheder" value={`${stats.online}/${devices.length}`} tone="success" />
        <Metric icon={<Film size={18} />} label="Optager nu" value={String(stats.recording)} tone="active" />
        <Metric icon={<QrCode size={18} />} label="Mangler provisioning" value={String(stats.unprovisioned)} tone="neutral" />
        <Metric icon={<UploadCloud size={18} />} label="Videoer med fejl" value={String(stats.failedVideos)} tone="danger" />
      </section>

      <section className="panel wide">
        <div className="panel-heading">
          <div>
            <h2>Fleet status</h2>
            <p>{selectedSite ? selectedSite.name : "Alle sites"} · {devices.length} enheder</p>
          </div>
          <button className="secondary-button" onClick={onOpenDevices}>
            <Plus size={16} />
            Opret enhed
          </button>
        </div>
        <div className="device-strip">
          {devices.length === 0 ? (
            <EmptyState title="Ingen enheder endnu" text="Opret første Raspberry Pi-enhed og generér provisioning-QR." />
          ) : (
            devices.map((device) => (
              <div key={device.id} className="device-tile">
                <span className={`status-dot ${statusClass[device.status]}`} />
                <strong>{device.display_name || device.serial_number}</strong>
                <span>{statusLabel[device.status]}</span>
                <small>{device.last_heartbeat_at ? relativeTime(device.last_heartbeat_at) : "Ingen heartbeat"}</small>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Seneste events</h2>
            <p>Driftsspor fra enheder</p>
          </div>
        </div>
        <EventList events={events} />
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Seneste videoer</h2>
            <p>{videos.length} registrerede videoer</p>
          </div>
        </div>
        <div className="compact-list">
          {videos.slice(0, 8).map((video) => (
            <div key={video.id} className="compact-row">
              <Film size={16} />
              <div>
                <strong>{video.scanned_id}</strong>
                <span>{videoDeviceLabel(video) || video.filename}</span>
              </div>
              <Badge tone={video.status === "failed" ? "danger" : "neutral"}>{video.status}</Badge>
            </div>
          ))}
          {videos.length === 0 && <EmptyState title="Ingen videoer endnu" text="Når Pi'en uploader metadata, vises optagelser her." />}
        </div>
      </section>
    </div>
  );
}

function DevicesView({
  devices,
  sites,
  deviceForm,
  setDeviceForm,
  onAddDevice,
  onProvision,
  onResetQr,
  onDeleteDevice,
}: {
  devices: Device[];
  sites: Site[];
  deviceForm: DeviceForm;
  setDeviceForm: (form: DeviceForm) => void;
  onAddDevice: (event: FormEvent) => void;
  onProvision: (device: Device) => void;
  onResetQr: (device: Device) => void;
  onDeleteDevice: (device: Device) => void;
}) {
  return (
    <div className="content-grid">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Opret enhed</h2>
            <p>Registrér Raspberry Pi før QR-provisioning</p>
          </div>
        </div>
        <form className="stack-form" onSubmit={onAddDevice}>
          <label>
            Serienummer
            <input
              value={deviceForm.serialNumber}
              onChange={(event) => setDeviceForm({ ...deviceForm, serialNumber: event.target.value })}
              placeholder="PP-000001"
            />
          </label>
          <label>
            Navn ved maskine
            <input
              value={deviceForm.displayName}
              onChange={(event) => setDeviceForm({ ...deviceForm, displayName: event.target.value })}
              placeholder="Foliering 01"
            />
          </label>
          <label>
            Site
            <select value={deviceForm.siteId} onChange={(event) => setDeviceForm({ ...deviceForm, siteId: event.target.value })}>
              {sites.map((site) => (
                <option key={site.id} value={site.id}>
                  {site.name}
                </option>
              ))}
            </select>
          </label>
          <button className="primary-button" type="submit">
            <Plus size={16} />
            Opret enhed
          </button>
        </form>
      </section>

      <section className="panel wide">
        <div className="panel-heading">
          <div>
            <h2>Enheder</h2>
            <p>{devices.length} registrerede enheder</p>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Enhed</th>
                <th>Status</th>
                <th>Software</th>
                <th>Temperatur</th>
                <th>Heartbeat</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {devices.map((device) => (
                <tr key={device.id}>
                  <td>
                    <strong>{device.display_name || device.serial_number}</strong>
                    <span>{device.serial_number}</span>
                  </td>
                  <td>
                    <Badge tone={statusClass[device.status]}>{statusLabel[device.status]}</Badge>
                  </td>
                  <td>{device.software_version || "-"}</td>
                  <td>{formatTemperature(device.metadata?.temperature_c)}</td>
                  <td>{device.last_heartbeat_at ? relativeTime(device.last_heartbeat_at) : "Aldrig"}</td>
                  <td className="row-actions">
                    <button className="icon-text-button" onClick={() => onProvision(device)}>
                      <QrCode size={16} />
                      QR
                    </button>
                    <button className="icon-text-button" onClick={() => onResetQr(device)}>
                      <RefreshCcw size={16} />
                      Reset
                    </button>
                    <button className="icon-button danger" onClick={() => onDeleteDevice(device)} aria-label={`Slet ${device.serial_number}`}>
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              ))}
              {devices.length === 0 && (
                <tr>
                  <td colSpan={6}>
                    <EmptyState title="Ingen enheder" text="Opret første enhed i formularen til venstre." />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function VideosView({
  videos,
  search,
  setSearch,
  onOpenVideo,
  onShare,
  shareResult,
  clearShare,
}: {
  videos: Video[];
  search: string;
  setSearch: (value: string) => void;
  onOpenVideo: (video: Video) => void;
  onShare: (video: Video) => void;
  shareResult: ShareResult | null;
  clearShare: () => void;
}) {
  return (
    <section className="panel full">
      <div className="panel-heading">
        <div>
          <h2>Videoer</h2>
          <p>Find optagelser efter scanned ID, fil eller enhed</p>
        </div>
        <label className="search-box">
          <Search size={16} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Søg scanned ID eller enhed" />
        </label>
      </div>

      {shareResult && (
        <div className="share-box">
          <div>
            <strong>Share-token oprettet</strong>
            <span>Public share-afspilning kobles på i næste backend-step.</span>
          </div>
          <button className="secondary-button" onClick={() => void copyText(shareResult.url)}>
            <Copy size={16} />
            Kopiér link
          </button>
          <button className="icon-button" onClick={clearShare} aria-label="Luk share-token">
            <ExternalLink size={16} />
          </button>
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Scanned ID</th>
              <th>Enhed</th>
              <th>Status</th>
              <th>Privatliv</th>
              <th>Tid</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {videos.map((video) => (
              <VideoRow key={video.id} video={video} onOpenVideo={onOpenVideo} onShare={onShare} />
            ))}
            {videos.length === 0 && (
              <tr>
                <td colSpan={6}>
                  <EmptyState title="Ingen videoer" text="Video-metadata dukker op her, når device API/upload-flowet er koblet på." />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function VideoRow({
  video,
  onOpenVideo,
  onShare,
}: {
  video: Video;
  onOpenVideo: (video: Video) => void;
  onShare: (video: Video) => void;
}) {
  const canUseVideo = video.status === "uploaded" && videoPrivacyReady(video);

  return (
    <tr>
      <td>
        <strong>{video.scanned_id}</strong>
        <span>{video.filename}</span>
      </td>
      <td>{videoDeviceLabel(video) || "-"}</td>
      <td>
        <Badge tone={video.status === "failed" ? "danger" : "neutral"}>{video.status}</Badge>
      </td>
      <td>
        <Badge tone={privacyTone(video.privacy_status)}>{privacyLabel(video.privacy_status)}</Badge>
      </td>
      <td>{video.created_at ? relativeTime(video.created_at) : "-"}</td>
      <td className="row-actions">
        <button
          className="icon-text-button"
          onClick={() => void onOpenVideo(video)}
          disabled={!canUseVideo}
          aria-label={`Se video ${video.scanned_id}`}
        >
          <Eye size={16} />
          Se
        </button>
        <button className="icon-text-button" onClick={() => void onShare(video)} disabled={!canUseVideo}>
          <Share2 size={16} />
          Del
        </button>
      </td>
    </tr>
  );
}

function VideoPlayerModal({ state, onClose }: { state: VideoPlayerState; onClose: () => void }) {
  const { video, playbackUrl, downloadUrl, loading, error } = state;

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal video-modal" role="dialog" aria-modal="true" aria-label="Videoafspiller">
        <div className="panel-heading">
          <div>
            <h2>{video.scanned_id}</h2>
            <p>{video.filename}</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Luk">
            ×
          </button>
        </div>

        <div className="video-player-frame">
          {loading && <ShellStateInline label="Henter video" />}
          {!loading && error && <EmptyState title="Videoen kunne ikke åbnes" text={error} />}
          {!loading && !error && playbackUrl && (
            <video className="video-player" src={playbackUrl} controls preload="metadata" playsInline />
          )}
        </div>

        <div className="modal-actions">
          {downloadUrl && (
            <a className="secondary-button" href={downloadUrl}>
              <Download size={16} />
              Download
            </a>
          )}
          <button className="secondary-button" type="button" onClick={onClose}>
            Luk
          </button>
        </div>
      </section>
    </div>
  );
}

function BillingView({
  prices,
  usage,
  canManageBilling,
  isPlatformAdmin,
  onEditEntitlement,
  onEditPrice,
}: {
  prices: BillingPrice[];
  usage: SiteBillingUsage[];
  canManageBilling: boolean;
  isPlatformAdmin: boolean;
  onEditEntitlement: (usage: SiteBillingUsage) => void;
  onEditPrice: (price: BillingPrice) => void;
}) {
  const hardwarePrice = priceFor(prices, "hardware_setup");
  const sitePrice = priceFor(prices, "site_service");
  const devicePrice = priceFor(prices, "device_license");
  const storagePrice = priceFor(prices, "storage_addon");
  const billableDevices = usage.reduce((sum, row) => sum + numberValue(row.billable_device_count), 0);
  const hardwarePending = usage.reduce((sum, row) => sum + numberValue(row.hardware_pending_count), 0);
  const extraStorageGb = usage.reduce((sum, row) => sum + numberValue(row.extra_storage_gb), 0);
  const monthlyEstimate =
    minorAmount(sitePrice) * usage.length +
    minorAmount(devicePrice) * billableDevices +
    minorAmount(storagePrice) * extraStorageGb;
  const hardwareEstimate = minorAmount(hardwarePrice) * hardwarePending;
  const currency = sitePrice?.currency || devicePrice?.currency || storagePrice?.currency || "DKK";

  return (
    <div className="content-grid">
      <section className="metrics-grid">
        <Metric icon={<CreditCard size={18} />} label="Est. månedlig base" value={formatMoney(monthlyEstimate, currency)} tone="active" />
        <Metric icon={<Boxes size={18} />} label="Hardware opstart" value={formatMoney(hardwareEstimate, currency)} tone="neutral" />
        <Metric icon={<HardDrive size={18} />} label="Billable enheder" value={String(billableDevices)} tone="neutral" />
        <Metric icon={<Database size={18} />} label="Ekstra storage" value={`${formatNumber(extraStorageGb)} GB`} tone="neutral" />
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Priskatalog</h2>
            <p>Komponenter der senere kobles til Stripe prices</p>
          </div>
        </div>
        <div className="price-list">
          <PriceRow price={hardwarePrice} fallback="Hardware opstart" isPlatformAdmin={isPlatformAdmin} onEditPrice={onEditPrice} />
          <PriceRow price={sitePrice} fallback="Service fee pr. site" isPlatformAdmin={isPlatformAdmin} onEditPrice={onEditPrice} />
          <PriceRow price={devicePrice} fallback="Softwarelicens pr. enhed" isPlatformAdmin={isPlatformAdmin} onEditPrice={onEditPrice} />
          <PriceRow price={storagePrice} fallback="Ekstra storage pr. GB" isPlatformAdmin={isPlatformAdmin} onEditPrice={onEditPrice} />
        </div>
      </section>

      <section className="panel wide">
        <div className="panel-heading">
          <div>
            <h2>Storage og entitlements</h2>
            <p>Ældste videoer kan slettes først, når auto-delete aktiveres og grænsen er nået</p>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Site</th>
                <th>Forbrug</th>
                <th>Videoer</th>
                <th>Enheder</th>
                <th>Retention</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {usage.map((row) => (
                <tr key={row.site_id}>
                  <td>
                    <strong>{row.site_name}</strong>
                    <span>{row.auto_delete_enabled ? "Auto-delete aktiv" : "Auto-delete slået fra"}</span>
                  </td>
                  <td>
                    <div className="storage-cell">
                      <div className="storage-bar" aria-label={`Storage usage ${row.usage_pct}%`}>
                        <span className={storageBarClass(row)} style={{ width: `${Math.min(100, numberValue(row.usage_pct))}%` }} />
                      </div>
                      <span>
                        {formatGb(row.used_storage_gb)} / {formatGb(row.total_storage_gb)}
                      </span>
                    </div>
                  </td>
                  <td>
                    <strong>{formatNumber(row.uploaded_video_count)}</strong>
                    <span>{row.shared_video_count} delt · {row.protected_video_count} protected</span>
                  </td>
                  <td>
                    <strong>{row.billable_device_count} billable</strong>
                    <span>{row.active_device_count} online/optager · {row.hardware_pending_count} hardware åbent</span>
                  </td>
                  <td>
                    <strong>{row.retention_days} dage</strong>
                    <span>{row.protect_shared_videos ? "Delt video beskyttes" : "Delt video kan slettes"}</span>
                  </td>
                  <td className="row-actions">
                    <button className="icon-text-button" onClick={() => onEditEntitlement(row)} disabled={!canManageBilling}>
                      <SlidersHorizontal size={16} />
                      Styr
                    </button>
                  </td>
                </tr>
              ))}
              {usage.length === 0 && (
                <tr>
                  <td colSpan={6}>
                    <EmptyState title="Ingen billing-data" text="Opret sites for at se storage og billing-entitlements." />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function PriceRow({
  price,
  fallback,
  isPlatformAdmin,
  onEditPrice,
}: {
  price: BillingPrice | undefined;
  fallback: string;
  isPlatformAdmin: boolean;
  onEditPrice: (price: BillingPrice) => void;
}) {
  return (
    <div className="price-row">
      <div>
        <strong>{price?.name || fallback}</strong>
        <span>{price?.description || "Ikke konfigureret endnu"}</span>
      </div>
      <div className="price-actions">
        <Badge tone={price && minorAmount(price) > 0 ? "active" : "neutral"}>
          {price ? `${formatMoney(minorAmount(price), price.currency)} / ${price.unit_label || price.billing_period}` : "Mangler"}
        </Badge>
        {price && isPlatformAdmin && (
          <button className="icon-text-button" onClick={() => onEditPrice(price)}>
            <SlidersHorizontal size={16} />
            Pris
          </button>
        )}
      </div>
    </div>
  );
}

function UpdatesView({
  rollouts,
  rolloutForm,
  setRolloutForm,
  onCreateRollout,
}: {
  rollouts: SoftwareRollout[];
  rolloutForm: RolloutForm;
  setRolloutForm: (form: RolloutForm) => void;
  onCreateRollout: (event: FormEvent) => void;
}) {
  return (
    <div className="content-grid">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Ny rollout</h2>
            <p>Registrér force eller night update</p>
          </div>
        </div>
        <form className="stack-form" onSubmit={onCreateRollout}>
          <label>
            Update ID
            <input
              value={rolloutForm.updateId}
              onChange={(event) => setRolloutForm({ ...rolloutForm, updateId: event.target.value })}
              placeholder="2026-07-23-scanner-fix-001"
            />
          </label>
          <label>
            Politik
            <select
              value={rolloutForm.policy}
              onChange={(event) => setRolloutForm({ ...rolloutForm, policy: event.target.value as "force" | "night" })}
            >
              <option value="night">Night</option>
              <option value="force">Force</option>
            </select>
          </label>
          <label>
            Version
            <input value={rolloutForm.version} onChange={(event) => setRolloutForm({ ...rolloutForm, version: event.target.value })} />
          </label>
          <label>
            Target ref
            <input value={rolloutForm.targetRef} onChange={(event) => setRolloutForm({ ...rolloutForm, targetRef: event.target.value })} />
          </label>
          <label>
            Target commit
            <input
              value={rolloutForm.targetCommit}
              onChange={(event) => setRolloutForm({ ...rolloutForm, targetCommit: event.target.value })}
              placeholder="Valgfri commit SHA"
            />
          </label>
          <label>
            Beskrivelse
            <textarea
              value={rolloutForm.description}
              onChange={(event) => setRolloutForm({ ...rolloutForm, description: event.target.value })}
              rows={3}
            />
          </label>
          <button className="primary-button" type="submit">
            {rolloutForm.policy === "force" ? <Zap size={16} /> : <Moon size={16} />}
            Opret rollout
          </button>
        </form>
      </section>

      <section className="panel wide">
        <div className="panel-heading">
          <div>
            <h2>Rollouts</h2>
            <p>{rollouts.length} registrerede updates</p>
          </div>
        </div>
        <div className="compact-list">
          {rollouts.map((rollout) => (
            <div key={rollout.id} className="rollout-row">
              <Badge tone={rollout.policy === "force" ? "active" : "neutral"}>{rollout.policy}</Badge>
              <div>
                <strong>{rollout.update_id}</strong>
                <span>{rollout.description || rollout.target_commit || rollout.target_ref}</span>
              </div>
              <small>{rollout.version || "-"}</small>
            </div>
          ))}
          {rollouts.length === 0 && <EmptyState title="Ingen rollouts" text="Når backend overtager updates, vises rollout-historik her." />}
        </div>
      </section>
    </div>
  );
}

function ProvisioningModal({
  device,
  form,
  setForm,
  qrImage,
  qrValue,
  onSubmit,
  onClose,
}: {
  device: Device;
  form: ProvisionForm;
  setForm: (form: ProvisionForm) => void;
  qrImage: string;
  qrValue: string;
  onSubmit: (event: FormEvent) => void;
  onClose: () => void;
}) {
  const [showWifiPassword, setShowWifiPassword] = useState(false);

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal" role="dialog" aria-modal="true" aria-label="Provisioning QR">
        <div className="panel-heading">
          <div>
            <h2>Provisioning-QR</h2>
            <p>{device.serial_number}</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Luk">
            ×
          </button>
        </div>
        <form className="stack-form" onSubmit={onSubmit}>
          <label>
            WiFi SSID
            <input value={form.wifiSsid} onChange={(event) => setForm({ ...form, wifiSsid: event.target.value })} />
          </label>
          <label>
            WiFi password
            <div className="password-field">
              <input
                type={showWifiPassword ? "text" : "password"}
                value={form.wifiPassword}
                onChange={(event) => setForm({ ...form, wifiPassword: event.target.value })}
              />
              <button
                className="icon-button"
                type="button"
                onClick={() => setShowWifiPassword((current) => !current)}
                aria-label={showWifiPassword ? "Skjul WiFi password" : "Vis WiFi password"}
              >
                {showWifiPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </label>
          <label>
            Udløber efter dage
            <input
              type="number"
              min={1}
              max={60}
              value={form.expiresDays}
              onChange={(event) => setForm({ ...form, expiresDays: Number(event.target.value) })}
            />
          </label>
          <button className="primary-button" type="submit">
            <Wifi size={16} />
            Generér QR
          </button>
        </form>
        {qrImage && (
          <div className="qr-result">
            <img src={qrImage} alt="Provisioning QR" />
            <div className="qr-actions">
              <button className="secondary-button" onClick={() => void copyText(qrValue)}>
                <Copy size={16} />
                Kopiér QR-data
              </button>
              <a className="secondary-button" href={qrImage} download={`${device.serial_number}-provisioning.png`}>
                <QrCode size={16} />
                Download PNG
              </a>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function ResetQrModal({
  device,
  qrImage,
  qrValue,
  onClose,
}: {
  device: Device;
  qrImage: string;
  qrValue: string;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal" role="dialog" aria-modal="true" aria-label="Reset QR">
        <div className="panel-heading">
          <div>
            <h2>Reset-QR</h2>
            <p>{device.serial_number}</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Luk">
            ×
          </button>
        </div>
        <p className="modal-copy">
          Scanner enheden denne QR-kode, fjernes den lokale provisioning på Pi'en. Historiske videoer bliver liggende på det site,
          hvor de blev optaget.
        </p>
        {qrImage && (
          <div className="qr-result">
            <img src={qrImage} alt="Reset QR" />
            <div className="qr-actions">
              <button className="secondary-button" onClick={() => void copyText(qrValue)}>
                <Copy size={16} />
                Kopiér QR-data
              </button>
              <a className="secondary-button" href={qrImage} download={`${device.serial_number}-reset.png`}>
                <QrCode size={16} />
                Download PNG
              </a>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function SiteEntitlementModal({
  usage,
  form,
  setForm,
  canManageBilling,
  onSubmit,
  onClose,
}: {
  usage: SiteBillingUsage;
  form: SiteEntitlementForm;
  setForm: (form: SiteEntitlementForm) => void;
  canManageBilling: boolean;
  onSubmit: (event: FormEvent) => void;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal" role="dialog" aria-modal="true" aria-label="Billing entitlement">
        <div className="panel-heading">
          <div>
            <h2>Billing-regler</h2>
            <p>{usage.site_name}</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Luk">
            ×
          </button>
        </div>
        {!canManageBilling && <p className="modal-copy">Kun organization owner/admin kan ændre billing-regler.</p>}
        <form className="stack-form" onSubmit={onSubmit}>
          <label>
            Inkluderet storage, GB
            <input
              type="number"
              min={0}
              step="0.01"
              value={form.includedStorageGb}
              onChange={(event) => setForm({ ...form, includedStorageGb: event.target.value })}
              disabled={!canManageBilling}
            />
          </label>
          <label>
            Ekstra storage, GB
            <input
              type="number"
              min={0}
              step="0.01"
              value={form.extraStorageGb}
              onChange={(event) => setForm({ ...form, extraStorageGb: event.target.value })}
              disabled={!canManageBilling}
            />
          </label>
          <label>
            Retention, dage
            <input
              type="number"
              min={1}
              step={1}
              value={form.retentionDays}
              onChange={(event) => setForm({ ...form, retentionDays: event.target.value })}
              disabled={!canManageBilling}
            />
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={form.autoDeleteEnabled}
              onChange={(event) => setForm({ ...form, autoDeleteEnabled: event.target.checked })}
              disabled={!canManageBilling}
            />
            Auto-delete ældste videoer ved pladsmangel
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={form.protectSharedVideos}
              onChange={(event) => setForm({ ...form, protectSharedVideos: event.target.checked })}
              disabled={!canManageBilling}
            />
            Beskyt videoer med aktive delingslinks
          </label>
          <div className="modal-actions">
            <button className="secondary-button" type="button" onClick={onClose}>
              Annuller
            </button>
            <button className="primary-button" type="submit" disabled={!canManageBilling}>
              <Check size={16} />
              Gem regler
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

function PriceModal({
  price,
  form,
  setForm,
  isPlatformAdmin,
  onSubmit,
  onClose,
}: {
  price: BillingPrice;
  form: PriceForm;
  setForm: (form: PriceForm) => void;
  isPlatformAdmin: boolean;
  onSubmit: (event: FormEvent) => void;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal" role="dialog" aria-modal="true" aria-label="Rediger pris">
        <div className="panel-heading">
          <div>
            <h2>Rediger pris</h2>
            <p>{price.name}</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Luk">
            ×
          </button>
        </div>
        {!isPlatformAdmin && <p className="modal-copy">Kun PalletProof platformadmin kan ændre priskataloget.</p>}
        <form className="stack-form" onSubmit={onSubmit}>
          <label>
            Pris ekskl. moms, {price.currency}
            <input
              type="number"
              min={0}
              step="0.01"
              value={form.unitAmount}
              onChange={(event) => setForm({ unitAmount: event.target.value })}
              disabled={!isPlatformAdmin}
            />
          </label>
          <p className="modal-copy">
            Enhed: {price.unit_label || price.billing_period}. Stripe price ID kan kobles på senere i metadata/webhook-laget.
          </p>
          <div className="modal-actions">
            <button className="secondary-button" type="button" onClick={onClose}>
              Annuller
            </button>
            <button className="primary-button" type="submit" disabled={!isPlatformAdmin}>
              <Check size={16} />
              Gem pris
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

function DeleteDeviceModal({
  device,
  onCancel,
  onConfirm,
}: {
  device: Device;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const [confirmation, setConfirmation] = useState("");
  const canDelete = confirmation === "SLET";
  const label = device.display_name || device.serial_number;

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (canDelete) {
      onConfirm();
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal" role="dialog" aria-modal="true" aria-label="Slet enhed">
        <div className="panel-heading">
          <div>
            <h2>Slet enhed</h2>
            <p>{label}</p>
          </div>
          <button className="icon-button" onClick={onCancel} aria-label="Luk">
            ×
          </button>
        </div>
        <form className="stack-form" onSubmit={handleSubmit}>
          <p className="danger-copy">
            Dette kan ikke fortrydes. Enheder med tilknyttede videoer kan ikke slettes.
          </p>
          <label>
            Skriv SLET for at fortsætte
            <input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoFocus />
          </label>
          <div className="modal-actions">
            <button className="secondary-button" type="button" onClick={onCancel}>
              Annuller
            </button>
            <button className="primary-button danger" type="submit" disabled={!canDelete}>
              <Trash2 size={16} />
              Slet enhed
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

function EventList({ events }: { events: DeviceEvent[] }) {
  if (events.length === 0) {
    return <EmptyState title="Ingen events" text="Heartbeat og device events vises her, når Pi'erne sender status." />;
  }

  return (
    <div className="compact-list">
      {events.map((event) => (
        <div key={event.id} className="compact-row">
          <ShieldCheck size={16} />
          <div>
            <strong>{event.event_type}</strong>
            <span>{event.message || relationLabel(event.devices, "serial_number") || "Device event"}</span>
          </div>
          <Badge tone={event.severity === "error" || event.severity === "critical" ? "danger" : "neutral"}>{event.severity}</Badge>
        </div>
      ))}
    </div>
  );
}

function Metric({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: string; tone: string }) {
  return (
    <section className={`metric ${tone}`}>
      <div>{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
    </section>
  );
}

function Badge({ children, tone }: { children: React.ReactNode; tone: string }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

function PalletProofMark({ size }: { size: number }) {
  return <img className="palletproof-mark" src="/palletproof-logo.svg" width={size} height={size} alt="PalletProof" />;
}

function NavButton({ active, icon, label, onClick }: { active: boolean; icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button className={`nav-button ${active ? "active" : ""}`} onClick={onClick}>
      {icon}
      {label}
    </button>
  );
}

function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <span>{text}</span>
    </div>
  );
}

function MissingConfiguration() {
  return (
    <main className="login-page">
      <section className="login-panel">
        <div className="brand-lockup">
          <div className="brand-mark">
            <PalletProofMark size={34} />
          </div>
          <div>
            <h1>Mangler Supabase config</h1>
            <p>Tilføj VITE_SUPABASE_URL og VITE_SUPABASE_ANON_KEY i web/.env.local.</p>
          </div>
        </div>
      </section>
    </main>
  );
}

function ShellState({ label }: { label: string }) {
  return (
    <main className="login-page">
      <section className="login-panel">
        <div className="brand-lockup">
          <div className="brand-mark">
            <PalletProofMark size={34} />
          </div>
          <div>
            <h1>PalletProof Admin</h1>
            <p>{label}</p>
          </div>
        </div>
      </section>
    </main>
  );
}

function ShellStateInline({ label }: { label: string }) {
  return (
    <div className="inline-state">
      <div className="loading-line" />
      <span>{label}</span>
    </div>
  );
}

function headingFor(tab: Tab) {
  if (tab === "devices") return "Enheder og provisioning";
  if (tab === "videos") return "Videoer og deling";
  if (tab === "billing") return "Billing og storage";
  if (tab === "updates") return "Software rollouts";
  return "Driftsoverblik";
}

function firstRelation<T>(value: T | T[] | null | undefined): T | null {
  if (!value) return null;
  return Array.isArray(value) ? value[0] ?? null : value;
}

function relationLabel<T extends Record<string, unknown>>(value: T | T[] | null | undefined, key: keyof T): string {
  const row = firstRelation(value);
  const label = row?.[key];
  return typeof label === "string" ? label : "";
}

function videoDeviceLabel(video: Video): string {
  return (
    video.device_display_name ||
    video.device_serial_number ||
    relationLabel(video.devices, "display_name") ||
    relationLabel(video.devices, "serial_number")
  );
}

function videoPrivacyReady(video: Video) {
  return video.privacy_status === "processed" || video.privacy_status === "not_required";
}

function privacyLabel(status: Video["privacy_status"]) {
  if (status === "processed") return "Processed";
  if (status === "not_required") return "Ikke påkrævet";
  if (status === "failed") return "Fejl";
  return "Afventer";
}

function privacyTone(status: Video["privacy_status"]) {
  if (status === "processed") return "success";
  if (status === "not_required") return "neutral";
  if (status === "failed") return "danger";
  return "active";
}

function priceFor(prices: BillingPrice[], component: BillingPrice["component"]) {
  return prices.find((price) => price.component === component && price.active);
}

function minorAmount(price: BillingPrice | undefined) {
  return price ? numberValue(price.unit_amount_minor) : 0;
}

function numberValue(value: unknown) {
  const number = typeof value === "number" ? value : typeof value === "string" ? Number(value) : 0;
  return Number.isFinite(number) ? number : 0;
}

function formatMoney(minor: number, currency = "DKK") {
  return new Intl.NumberFormat("da-DK", {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(minor / 100);
}

function formatNumber(value: unknown) {
  return new Intl.NumberFormat("da-DK", {
    maximumFractionDigits: 2,
  }).format(numberValue(value));
}

function formatGb(value: unknown) {
  return `${formatNumber(value)} GB`;
}

function storageBarClass(row: SiteBillingUsage) {
  const pct = numberValue(row.usage_pct);
  if (pct >= numberValue(row.critical_threshold_pct)) return "critical";
  if (pct >= numberValue(row.warning_threshold_pct)) return "warning";
  return "ok";
}

function uniqueOrganizations(memberships: Membership[]): Organization[] {
  const byId = new Map<string, Organization>();
  for (const membership of memberships) {
    const organization = firstRelation(membership.organizations);
    if (organization) {
      byId.set(organization.id, organization);
    }
  }
  return Array.from(byId.values()).sort((a, b) => a.name.localeCompare(b.name));
}

function currentMembershipRowsToMemberships(rows: CurrentMembershipRow[]): Membership[] {
  return rows.map((row) => ({
    id: row.membership_id,
    organization_id: row.organization_id,
    site_id: row.site_id,
    role: row.role,
    organizations: {
      id: row.organization_id,
      name: row.organization_name,
      slug: row.organization_slug,
    },
    sites: row.site_id
      ? {
          id: row.site_id,
          organization_id: row.organization_id,
          name: row.site_name ?? "",
          slug: row.site_slug ?? "",
          timezone: row.site_timezone ?? "Europe/Copenhagen",
        }
      : null,
  }));
}

function relativeTime(value: string) {
  const then = new Date(value).getTime();
  const diff = Date.now() - then;
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return "nu";
  if (minutes < 60) return `${minutes} min siden`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} timer siden`;
  const days = Math.round(hours / 24);
  return `${days} dage siden`;
}

function formatTemperature(value: unknown) {
  const temperature = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  if (!Number.isFinite(temperature)) {
    return "-";
  }
  return `${temperature.toFixed(1)} °C`;
}

function randomToken(bytes: number) {
  const values = new Uint8Array(bytes);
  crypto.getRandomValues(values);
  return bytesToBase64Url(values);
}

async function sha256Hex(value: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function base64UrlJson(value: unknown) {
  return bytesToBase64Url(new TextEncoder().encode(JSON.stringify(value)));
}

function bytesToBase64Url(values: Uint8Array) {
  let binary = "";
  values.forEach((value) => {
    binary += String.fromCharCode(value);
  });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function safeIdentifier(value: string) {
  return value.replace(/[^A-Za-z0-9_.-]/g, "-").slice(0, 64) || "default";
}

async function copyText(value: string) {
  await navigator.clipboard.writeText(value);
}

function errorMessage(caught: unknown) {
  if (caught instanceof Error) return caught.message;
  if (typeof caught === "string") return caught;
  if (caught && typeof caught === "object") {
    const values = caught as { message?: unknown; details?: unknown; hint?: unknown; code?: unknown };
    const parts = [values.message, values.details, values.hint, values.code]
      .filter((value): value is string => typeof value === "string" && value.length > 0);
    if (parts.length > 0) {
      return parts.join(" · ");
    }
    try {
      return JSON.stringify(caught);
    } catch {
      return "Der opstod en ukendt fejl.";
    }
  }
  return "Der opstod en ukendt fejl.";
}

export default App;
