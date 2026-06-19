const MQTT_CFG = {
    url: 'wss://5031841c1f8d4218bafa640220641d55.s1.eu.hivemq.cloud:8884/mqtt',
    options: {
        username: 'lhuy04',
        password: 'Hcmute2026',
        protocol: 'wss',
        port: 8884,
        clean: true,
        connectTimeout: 4000
    }
};

function getClientId(prefix = 'web') {
    return `${prefix}_${Math.random().toString(16).substr(2, 8)}`;
}

function authGuard() {
    const token  = sessionStorage.getItem('_at');
    const expiry = parseInt(sessionStorage.getItem('_ae') || '0');
    if (!token || Date.now() > expiry) {
        sessionStorage.clear();
        localStorage.removeItem('isLoggedIn');
        location.href = 'login.html';
    }
}

function doLogout() {
    sessionStorage.clear();
    localStorage.removeItem('isLoggedIn');
    localStorage.removeItem('plcConnected');
    location.href = 'index.html';
}

const _escMap = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#x27;' };
function escapeHtml(str) {
    return String(str ?? '').replace(/[&<>"']/g, c => _escMap[c]);
}

function computeStats(data) {
    const hourImp = Array(12).fill(0), hourExp = Array(12).fill(0);
    const slotImp = Array(9).fill(0),  slotExp = Array(9).fill(0);
    let imports = 0, exports = 0;
    data.forEach(item => {
        const act  = (item.act || item.action || '').toUpperCase();
        const idx  = parseInt(String(item.time || item.timestamp || '0').split(':')[0]) - 6;
        const sNum = parseInt(String(item.slot || item.slot_id || '0').replace(/\D/g, '')) - 1;
        if (act === 'IMPORT') imports++;
        else if (act === 'EXPORT') exports++;
        if (idx >= 0 && idx < 12) { act === 'IMPORT' ? hourImp[idx]++ : act === 'EXPORT' ? hourExp[idx]++ : 0; }
        if (sNum >= 0 && sNum < 9) { act === 'IMPORT' ? slotImp[sNum]++ : act === 'EXPORT' ? slotExp[sNum]++ : 0; }
    });
    return { imports, exports, hourImp, hourExp, slotImp, slotExp };
}

function initMaintMode() {
    if (typeof window === 'undefined' || window.location.pathname.includes('login.html')) return;

    function loadScript(src, cb) {
        if(document.querySelector(`script[src="${src}"]`)) return cb();
        const s = document.createElement('script');
        s.src = src; s.onload = cb; document.head.appendChild(s);
    }

    loadScript("https://cdn.jsdelivr.net/npm/sweetalert2@11", () => {
        loadScript("https://cdn.jsdelivr.net/npm/mqtt@5.3.4/dist/mqtt.min.js", () => {
            const maintClient = mqtt.connect(MQTT_CFG.url, { ...MQTT_CFG.options, clientId: getClientId('maint') });

            maintClient.on('connect', () => {
                maintClient.subscribe('asrs/cmd/change_mode');
                maintClient.subscribe('warehouse/maintenance_mode');
            });

            let maintStartTime = null;
            let _maintActive = false;

            function showMaintDialog() {
                if (_maintActive) return;
                _maintActive = true;
                if (!maintStartTime) maintStartTime = new Date();
                const startStr = maintStartTime.toISOString().replace('T', ' ').split('.')[0];
                Swal.fire({
                    background: '#1e2130',
                    color: '#e0e0e0',
                    showConfirmButton: false,
                    allowOutsideClick: false,
                    allowEscapeKey: false,
                    width: '420px',
                    padding: '40px 36px',
                    customClass: { popup: 'asrs-maint-popup' },
                    html: `
                        <style>
                            .asrs-maint-popup { border: 2px solid #f59e0b !important; border-radius: 18px !important; }
                        </style>
                        <div style="font-size:64px; margin-bottom:16px;">🔒</div>
                        <div style="font-family:'Orbitron',sans-serif; font-size:22px; font-weight:800;
                                    color:#f59e0b; letter-spacing:1px; margin-bottom:16px; text-transform:uppercase;">
                            System Under Maintenance
                        </div>
                        <div style="font-size:14px; color:#9ca3af; line-height:1.7; margin-bottom:24px;">
                            The ASRS system is currently in <strong style="color:#f59e0b;">MANUAL</strong> mode.<br>
                            Please wait until maintenance is complete to continue.
                        </div>
                        <div style="display:inline-flex; align-items:center; gap:8px;
                                    background:rgba(245,158,11,0.1); border:1px solid rgba(245,158,11,0.5);
                                    border-radius:999px; padding:8px 20px; font-size:12px;
                                    font-weight:700; letter-spacing:1px; color:#f59e0b;">
                            <span style="width:8px;height:8px;background:#f59e0b;border-radius:50%;
                                         animation:swal-pulse 1s infinite;display:inline-block;"></span>
                            MAINTENANCE MODE ACTIVE
                        </div>
                        <div style="margin-top:18px; font-size:11px; color:#6b7280;">
                            Started: ${startStr}
                        </div>
                        <style>
                            @keyframes swal-pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
                        </style>
                    `
                });
            }

            function hideMaintDialog() {
                if (!_maintActive) return;
                _maintActive = false;
                maintStartTime = null;
                Swal.close();
            }

            maintClient.on('message', (t, m) => {
                try {
                    const data = JSON.parse(m.toString());
                    // Handle topic 'asrs/cmd/change_mode' from asrs_maintenance
                    if (t === 'asrs/cmd/change_mode') {
                        if (data.mode === 'MANUAL') showMaintDialog();
                        else if (data.mode === 'AUTO') hideMaintDialog();
                    }
                    // Handle topic 'warehouse/maintenance_mode' from Python backend
                    if (t === 'warehouse/maintenance_mode') {
                        const active = data.active === true || data.active === 'true' || data.active === 1;
                        if (active) showMaintDialog();
                        else hideMaintDialog();
                    }
                } catch(e) {}
            });
        });
    });
}
initMaintMode();

