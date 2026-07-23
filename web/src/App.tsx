import { FormEvent, useEffect, useMemo, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import QRCode from "qrcode";
import {
  Activity,
  Boxes,
  Check,
  Copy,
  ExternalLink,
  Film,
  KeyRound,
  LogOut,
  Moon,
  Plus,
  QrCode,
  RefreshCcw,
  Search,
  Share2,
  ShieldCheck,
  UploadCloud,
  Wifi,
  Zap,
} from "lucide-react";
import { isSupabaseConfigured, requireSupabase, supabaseUrl } from "./supabase";
import type { CurrentMembershipRow, Device, DeviceEvent, Membership, Organization, Site, SoftwareRollout, Video } from "./types";

type Tab = "overview" | "devices" | "videos" | "updates";

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

type ShareResult = {
  url: string;
  token: string;
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
  const [selectedOrgId, setSelectedOrgId] = useState("");
  const [selectedSiteId, setSelectedSiteId] = useState("all");
  const [deviceForm, setDeviceForm] = useState<DeviceForm>(emptyDeviceForm);
  const [provisionDevice, setProvisionDevice] = useState<Device | null>(null);
  const [provisionForm, setProvisionForm] = useState<ProvisionForm>(emptyProvisionForm);
  const [qrValue, setQrValue] = useState("");
  const [qrImage, setQrImage] = useState("");
  const [rolloutForm, setRolloutForm] = useState<RolloutForm>(emptyRolloutForm);
  const [shareResult, setShareResult] = useState<ShareResult | null>(null);
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
  const recentEvents = events.slice(0, 8);
  const visibleVideos = videos.filter((video) => {
    const needle = search.trim().toLowerCase();
    if (!needle) {
      return true;
    }
    return `${video.order_number} ${video.filename} ${relationLabel(video.devices, "serial_number")}`
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
        .select("*, devices(serial_number, display_name), sites(name)")
        .eq("organization_id", effectiveOrgId)
        .order("created_at", { ascending: false })
        .limit(100);
      let eventQuery = client
        .from("device_events")
        .select("*, devices(serial_number, display_name)")
        .eq("organization_id", effectiveOrgId)
        .order("created_at", { ascending: false })
        .limit(50);

      if (effectiveSiteId !== "all") {
        deviceQuery = deviceQuery.eq("site_id", effectiveSiteId);
        videoQuery = videoQuery.eq("site_id", effectiveSiteId);
        eventQuery = eventQuery.eq("site_id", effectiveSiteId);
      }

      const [deviceResult, videoResult, eventResult, rolloutResult] = await Promise.all([
        deviceQuery,
        videoQuery,
        eventQuery,
        client.from("software_rollouts").select("*").order("created_at", { ascending: false }).limit(20),
      ]);

      if (deviceResult.error) throw deviceResult.error;
      if (videoResult.error) throw videoResult.error;
      if (eventResult.error) throw eventResult.error;
      if (rolloutResult.error) throw rolloutResult.error;

      setDevices((deviceResult.data ?? []) as Device[]);
      setVideos((videoResult.data ?? []) as Video[]);
      setEvents((eventResult.data ?? []) as DeviceEvent[]);
      setRollouts((rolloutResult.data ?? []) as SoftwareRollout[]);
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
    const { error: insertError } = await client.from("devices").insert({
      organization_id: selectedOrganization.id,
      site_id: siteId,
      serial_number: serialNumber,
      display_name: deviceForm.displayName.trim(),
      status: "unprovisioned",
    });

    if (insertError) {
      setError(insertError.message);
      return;
    }

    setDeviceForm({ ...emptyDeviceForm, siteId });
    setNotice(`Enhed ${serialNumber} er oprettet.`);
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
      setNotice(`Share-token oprettet for ${video.order_number}.`);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  function openProvisioning(device: Device) {
    setProvisionDevice(device);
    setProvisionForm(emptyProvisionForm);
    setQrValue("");
    setQrImage("");
    setError("");
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
              <Boxes size={24} />
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
            <Boxes size={22} />
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
              />
            )}

            {tab === "videos" && (
              <VideosView
                videos={visibleVideos}
                search={search}
                setSearch={setSearch}
                onShare={handlePrepareShare}
                shareResult={shareResult}
                clearShare={() => setShareResult(null)}
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
                <strong>{video.order_number}</strong>
                <span>{relationLabel(video.devices, "serial_number") || video.filename}</span>
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
}: {
  devices: Device[];
  sites: Site[];
  deviceForm: DeviceForm;
  setDeviceForm: (form: DeviceForm) => void;
  onAddDevice: (event: FormEvent) => void;
  onProvision: (device: Device) => void;
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
                  <td>{device.last_heartbeat_at ? relativeTime(device.last_heartbeat_at) : "Aldrig"}</td>
                  <td className="row-actions">
                    <button className="icon-text-button" onClick={() => onProvision(device)}>
                      <QrCode size={16} />
                      QR
                    </button>
                  </td>
                </tr>
              ))}
              {devices.length === 0 && (
                <tr>
                  <td colSpan={5}>
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
  onShare,
  shareResult,
  clearShare,
}: {
  videos: Video[];
  search: string;
  setSearch: (value: string) => void;
  onShare: (video: Video) => void;
  shareResult: ShareResult | null;
  clearShare: () => void;
}) {
  return (
    <section className="panel full">
      <div className="panel-heading">
        <div>
          <h2>Videoer</h2>
          <p>Find optagelser efter ordre, fil eller enhed</p>
        </div>
        <label className="search-box">
          <Search size={16} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Søg ordre eller enhed" />
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
              <th>Ordre</th>
              <th>Enhed</th>
              <th>Status</th>
              <th>Privatliv</th>
              <th>Tid</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {videos.map((video) => (
              <tr key={video.id}>
                <td>
                  <strong>{video.order_number}</strong>
                  <span>{video.filename}</span>
                </td>
                <td>{relationLabel(video.devices, "display_name") || relationLabel(video.devices, "serial_number") || "-"}</td>
                <td>
                  <Badge tone={video.status === "failed" ? "danger" : "neutral"}>{video.status}</Badge>
                </td>
                <td>{video.privacy_status}</td>
                <td>{video.created_at ? relativeTime(video.created_at) : "-"}</td>
                <td className="row-actions">
                  <button className="icon-text-button" onClick={() => void onShare(video)}>
                    <Share2 size={16} />
                    Del
                  </button>
                </td>
              </tr>
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
            <input
              type="password"
              value={form.wifiPassword}
              onChange={(event) => setForm({ ...form, wifiPassword: event.target.value })}
            />
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
            <Boxes size={24} />
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
            <Boxes size={24} />
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

function headingFor(tab: Tab) {
  if (tab === "devices") return "Enheder og provisioning";
  if (tab === "videos") return "Videoer og deling";
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
  return "Der opstod en ukendt fejl.";
}

export default App;
