/* ============================================================
   CYBER DATA NEXUS — pages.js
   ============================================================ */

/* NexusAuth — ОБОВ'ЯЗКОВО ДО DOMContentLoaded */
window.NexusAuth = {
  saveTokens(a, r) {
    sessionStorage.setItem('nexus_access', a);
    sessionStorage.setItem('nexus_refresh', r);
  },
  getAccess()  { return sessionStorage.getItem('nexus_access');  },
  getRefresh() { return sessionStorage.getItem('nexus_refresh'); },
  clear() {
    sessionStorage.removeItem('nexus_access');
    sessionStorage.removeItem('nexus_refresh');
  },
  async authFetch(url, opts = {}) {
    const token = this.getAccess();
    opts.headers = { 'Content-Type': 'application/json', ...opts.headers };
    if (token) opts.headers['Authorization'] = 'Bearer ' + token;
    let res = await fetch(url, opts);
    if (res.status === 401) {
      const rt = this.getRefresh();
      if (rt) {
        const rr = await fetch('/api/auth/refresh', {
          method: 'POST', headers: {'Content-Type':'application/json'},
          body: JSON.stringify({ refresh_token: rt }),
        });
        if (rr.ok) {
          const rd = await rr.json();
          this.saveTokens(rd.access_token, rd.refresh_token);
          opts.headers['Authorization'] = 'Bearer ' + rd.access_token;
          res = await fetch(url, opts);
        } else {
          this.clear();
          window.location.href = '/home';
          return null;
        }
      }
    }
    return res;
  },
};

document.addEventListener('DOMContentLoaded', async () => {

  /* ═══════════════════════════════════
     LANDING PAGE
  ═══════════════════════════════════ */
  if (document.querySelector('.landing-wrap')) {
    // Animated counters
    const animateCount = el => {
      const target = parseFloat(el.dataset.count), suffix = el.dataset.suffix||'';
      const start  = performance.now();
      const step   = now => {
        const p = Math.min((now-start)/1800,1), ease=1-Math.pow(1-p,3);
        el.textContent = (target<10?(target*ease).toFixed(1):Math.round(target*ease))+suffix;
        if (p<1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    };
    document.querySelectorAll('[data-count]').forEach(el => {
      new IntersectionObserver(entries => {
        entries.forEach(e => { if(e.isIntersecting) animateCount(e.target); });
      }, {threshold:0.5}).observe(el);
    });
    // Feature cards
    document.head.insertAdjacentHTML('beforeend',
      '<style>.card-visible{opacity:1!important;transform:translateY(0)!important}</style>');
    document.querySelectorAll('.feature-card').forEach(c => {
      c.style.cssText='opacity:0;transform:translateY(20px);transition:opacity .5s,transform .5s';
      new IntersectionObserver(entries=>{
        entries.forEach(e=>{ if(e.isIntersecting) e.target.classList.add('card-visible'); });
      },{threshold:0.15}).observe(c);
    });
  }


  /* ═══════════════════════════════════
     AUTH PAGE
  ═══════════════════════════════════ */
  if (document.querySelector('.auth-card')) {
    // Tab switching
    document.querySelectorAll('.auth-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.auth-tab').forEach(t=>t.classList.remove('active'));
        document.querySelectorAll('.auth-form').forEach(f=>{
          f.style.display = f.dataset.form===tab.dataset.tab ? 'block' : 'none';
        });
        tab.classList.add('active');
        document.getElementById('authTitle').textContent =
          tab.dataset.tab==='login' ? 'Welcome back' : 'Create account';
        document.getElementById('authSubtitle').textContent = tab.dataset.tab==='login'
          ? 'Sign in to your CYBER DATA NEXUS workspace'
          : 'Join thousands of users managing their data';
      });
    });

    // Password toggle
    document.querySelectorAll('.form-input-icon[data-toggle-pass]').forEach(btn => {
      btn.addEventListener('click', () => {
        const inp = btn.previousElementSibling; if(!inp) return;
        inp.type = inp.type==='password' ? 'text' : 'password';
        btn.textContent = inp.type==='password' ? '👁' : '🙈';
      });
    });

    // Password strength meter
    const regPwd = document.getElementById('regPassword');
    const bar    = document.querySelector('.password-strength-bar');
    if (regPwd && bar) {
      regPwd.addEventListener('input', () => {
        const v=regPwd.value;
        const s=[v.length>=8,/[A-Z]/.test(v),/\d/.test(v),/[^A-Za-z0-9]/.test(v)].filter(Boolean).length;
        bar.style.width=['0%','25%','50%','75%','100%'][s];
        bar.style.background=['','#ff4757','#ffa500','#00b8ff','#00ffc8'][s]||'';
        const st=document.querySelector('.strength-text');
        if(st){st.textContent=['','Weak','Fair','Good','Strong'][s]||'';st.style.color=bar.style.background;}
      });
    }

    // ── LOGIN ──
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
      loginForm.addEventListener('submit', async e => {
        e.preventDefault();
        const btn   = loginForm.querySelector('.btn-full');
        const email = loginForm.querySelector('input[type=email]').value.trim();
        const pwd   = loginForm.querySelector('input[type=password]')?.value || '';
        const rem   = loginForm.querySelector('#rememberMe')?.checked ?? false;
        btn.textContent='⚡ Authenticating…'; btn.disabled=true;
        try {
          const res  = await fetch('/api/auth/login',{
            method:'POST', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({email, password:pwd, remember_me:rem}),
          });
          const data = await res.json();
          if (data.success) {
            NexusAuth.saveTokens(data.access_token, data.refresh_token);
            window.location.href = '/';   // → index() → дешборд (login_required вже пройдено)
          } else {
            showToast('❌ '+(data.error||'Login failed'),'error');
            btn.textContent='⚡ Sign In'; btn.disabled=false;
          }
        } catch {
          showToast('❌ Network error','error');
          btn.textContent='⚡ Sign In'; btn.disabled=false;
        }
      });
    }

    // ── REGISTER ──
    const regForm = document.getElementById('registerForm');
    if (regForm) {
      regForm.addEventListener('submit', async e => {
        e.preventDefault();
        const btn      = regForm.querySelector('.btn-full');
        const firstName= regForm.querySelector('input[placeholder="Neo"]')?.value.trim()||'';
        const lastName = regForm.querySelector('input[placeholder="Anderson"]')?.value.trim()||'';
        const username = regForm.querySelector('input[placeholder="@cyber_user"]')?.value.trim()||'';
        const email    = regForm.querySelector('input[type=email]')?.value.trim()||'';
        const password = document.getElementById('regPassword')?.value||'';
        const allPwds  = regForm.querySelectorAll('input[type=password]');
        const confirm  = allPwds[allPwds.length-1]?.value||'';
        if (password!==confirm){showToast('❌ Passwords do not match','error');return;}
        btn.textContent='⚡ Creating account…'; btn.disabled=true;
        try {
          const res  = await fetch('/api/auth/register',{
            method:'POST', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({first_name:firstName,last_name:lastName,username,email,password}),
          });
          const data = await res.json();
          if (data.success) {
            NexusAuth.saveTokens(data.access_token, data.refresh_token);
            window.location.href = '/';
          } else {
            const msg = data.errors?data.errors.join(' '):'Registration failed';
            showToast('❌ '+msg,'error');
            btn.textContent='⚡ Create Account'; btn.disabled=false;
          }
        } catch {
          showToast('❌ Network error','error');
          btn.textContent='⚡ Create Account'; btn.disabled=false;
        }
      });
    }
  } // end auth page


  /* ═══════════════════════════════════
     PROFILE PAGE
     Дані передаються через window.__NEXUS_USER__ (Jinja),
     тому працює навіть без JWT/sessionStorage після reload.
  ═══════════════════════════════════ */
  if (document.querySelector('.profile-wrap')) {

    // Tab switching
    document.querySelectorAll('.profile-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.profile-tab').forEach(t=>t.classList.remove('active'));
        document.querySelectorAll('.tab-pane').forEach(p=>{p.classList.remove('active');});
        tab.classList.add('active');
        const pane = document.getElementById('pane-'+tab.dataset.pane);
        if (pane) pane.classList.add('active');
      });
    });

    // Всі поля заблоковані при старті
    document.querySelectorAll('.info-field-value').forEach(f=>{
      f.setAttribute('readonly',''); f.setAttribute('disabled','');
    });
    document.querySelectorAll('.save-row').forEach(r=>r.style.display='none');

    // Edit toggle
    document.querySelectorAll('.edit-toggle-btn').forEach(btn=>{
      btn.addEventListener('click',()=>{
        const card=btn.closest('.profile-card');
        if(btn.dataset.editing==='true'){ _cancelEdit(card); return; }
        // Розблокуємо тільки редаговані поля (без data-readonly)
        card.querySelectorAll('.info-field-value:not([data-readonly])').forEach(f=>{
          f.removeAttribute('readonly'); f.removeAttribute('disabled');
          f.style.background='rgba(0,255,200,.04)'; f.style.borderColor='rgba(0,255,200,.25)';
        });
        const sr=card.querySelector('.save-row');
        if(sr) sr.style.display='flex';
        btn.textContent='✕ Cancel'; btn.dataset.editing='true';
      });
    });

    // Cancel
    document.querySelectorAll('.btn-cancel').forEach(btn=>{
      btn.addEventListener('click',()=>{ const c=btn.closest('.profile-card'); if(c)_cancelEdit(c); });
    });

    function _cancelEdit(card){
      card.querySelectorAll('.info-field-value').forEach(f=>{
        f.setAttribute('readonly',''); f.setAttribute('disabled','');
        f.style.background=''; f.style.borderColor='';
      });
      const sr=card.querySelector('.save-row'); if(sr) sr.style.display='none';
      const eb=card.querySelector('.edit-toggle-btn');
      if(eb){eb.textContent='✏️ Edit'; eb.dataset.editing='false';}
    }

    // Save — збирає data-field і робить PUT /api/auth/me
    document.querySelectorAll('.btn-save').forEach(btn=>{
      btn.addEventListener('click', async ()=>{
        const card=btn.closest('.profile-card');
        const payload={};
        card.querySelectorAll('.info-field-value[data-field]:not([data-readonly])').forEach(f=>{
          payload[f.dataset.field]=f.value.trim();
        });
        if(!Object.keys(payload).length){ _cancelEdit(card); return; }
        btn.textContent='⏳ Saving…'; btn.disabled=true;
        try {
          const res=await NexusAuth.authFetch('/api/auth/me',{method:'PUT',body:JSON.stringify(payload)});
          if(!res){ showToast('❌ Not authenticated','error'); return; }
          const data=await res.json();
          if(data.success){ showToast('✅ Changes saved'); _cancelEdit(card); }
          else showToast('❌ '+(data.error||'Save failed'),'error');
        } catch { showToast('❌ Network error','error'); }
        finally { btn.textContent='💾 Save Changes'; btn.disabled=false; }
      });
    });

    // Sign out
    document.getElementById('signOutBtn')?.addEventListener('click', async ()=>{
      try { await NexusAuth.authFetch('/api/auth/logout',{method:'POST'}); } catch {}
      NexusAuth.clear();
      window.location.href = '/home';   // → лендінг напряму, без login_required loop
    });

    // ── Рендеримо профіль з Jinja-даних ──
    const u = window.__NEXUS_USER__;   // встановлюється в profile.html через {{ user_json|safe }}
    if (u) {
      renderProfile(u);
    } else {
      showToast('⚠️ Could not load profile data','error');
    }
  } // end profile page


  /* ═══════════════════════════════════
     RENDER PROFILE
  ═══════════════════════════════════ */
  function renderProfile(u) {
    // Hero name
    const nameEl = document.getElementById('profileDisplayName');
    if (nameEl) nameEl.innerHTML = esc(u.display_name) +
      (u.is_verified?' <span class="profile-badge-verify">✓ VERIFIED</span>':'');

    // Username row
    const ur = document.getElementById('profileUsernameRow');
    if (ur) ur.textContent = `@${u.username} · Member since ${
      u.created_at ? new Date(u.created_at).getFullYear() : '—'}`;

    // Role tags
    const tagsEl = document.getElementById('profileRoleTags');
    if (tagsEl) {
      const em={admin:'👑',editor:'✏️',viewer:'👁'}, lb={admin:'Admin',editor:'Editor',viewer:'Viewer'};
      tagsEl.innerHTML = `<span class="profile-tag">${em[u.role]||'👤'} ${lb[u.role]||u.role}</span>`+
        (u.is_verified?'<span class="profile-tag">✓ Verified</span>':'');
    }

    // Stats bar
    const fmt=b=>!b?'0 B':b>1e9?(b/1e9).toFixed(1)+' GB':b>1e6?(b/1e6).toFixed(0)+' MB':(b/1024).toFixed(0)+' KB';
    _txt('statFiles',      u.stats?.total_files??'—');
    _txt('statStorage',    fmt(u.stats?.total_size));
    _txt('statCategories', u.stats?.categories??'—');
    _txt('statTags',       u.stats?.total_tags??'—');
    const re=document.getElementById('statRole');
    if(re){re.textContent=(u.role||'—').toUpperCase();re.style.fontSize='.85rem';}

    // Заповнюємо поля форм через data-field
    const fieldMap={
      first_name:u.first_name||'', last_name:u.last_name||'',
      phone:u.phone||'', location:u.location||'', bio:u.bio||'',
      language:u.language||'', timezone:u.timezone||'',
      email:u.email||'',                         // readonly
      username:'@'+(u.username||''),             // readonly
    };
    Object.entries(fieldMap).forEach(([k,v])=>{
      document.querySelectorAll(`[data-field="${k}"]`).forEach(el=>{ el.value=v; });
    });

    // ── Управління доступом по ролі ──
    if (u.role === 'admin') {
      // Показуємо Admin tab і вміст
      document.querySelectorAll('.admin-only').forEach(el=>el.style.display='');
      loadAdminData();
    } else {
      // Ховаємо всі admin-only елементи
      document.querySelectorAll('.admin-only').forEach(el=>el.style.display='none');
    }

    // Upload button в Quick Actions — тільки editor+
    if (u.role === 'viewer') {
      // Повністю ховаємо upload кнопку для viewer
      document.querySelectorAll('.editor-only').forEach(el=>{
        el.style.display = 'none';
      });
      // Показуємо Request Access card
      const rac = document.getElementById('requestAccessCard');
      if (rac) rac.style.display='';
      loadMyRoleRequest();
      initRoleRequestForm();
    }
  }

  // ── Role Request (viewer) ──
  async function loadMyRoleRequest() {
    try {
      const res = await NexusAuth.authFetch('/api/role-request/my');
      if (!res?.ok) return;
      const d = await res.json();
      const form       = document.getElementById('roleReqForm');
      const pending    = document.getElementById('roleReqStatus');
      const approved   = document.getElementById('roleReqApproved');
      const rejected   = document.getElementById('roleReqRejected');

      // Reset all
      [pending, approved, rejected].forEach(el=>{ if(el) el.style.display='none'; });

      if (d.request) {
        const st = d.request.status;
        if (st === 'pending') {
          if (form) form.style.display = 'none';
          if (pending) { pending.style.display = ''; pending.textContent = `⏳ Request for "${d.request.requested_role}" is pending review…`; }
        } else if (st === 'approved') {
          if (form) form.style.display = 'none';
          if (approved) approved.style.display = '';
        } else if (st === 'rejected') {
          // Show rejected notice + allow resubmit
          if (rejected) rejected.style.display = '';
          if (form) form.style.display = '';
        }
      }
    } catch {}
  }

  function initRoleRequestForm() {
    document.getElementById('submitRoleReqBtn')?.addEventListener('click', async () => {
      const btn = document.getElementById('submitRoleReqBtn');
      const role = document.getElementById('reqRoleSelect')?.value || 'editor';
      const message = document.getElementById('reqRoleMessage')?.value || '';
      btn.textContent = '⏳ Sending…'; btn.disabled = true;
      try {
        const res = await NexusAuth.authFetch('/api/role-request', {
          method: 'POST', body: JSON.stringify({ role, message })
        });
        const d = await res?.json();
        if (d?.success) {
          showToast('✅ Request sent! Admin will review it shortly.');
          const form    = document.getElementById('roleReqForm');
          const pending = document.getElementById('roleReqStatus');
          const rejected = document.getElementById('roleReqRejected');
          if (form) form.style.display = 'none';
          if (rejected) rejected.style.display = 'none';
          if (pending) { pending.style.display = ''; pending.textContent = `⏳ Request for "${role}" is pending review…`; }
        } else {
          showToast('❌ ' + (d?.error || 'Failed to send'), 'error');
          btn.textContent = '📨 Send Request'; btn.disabled = false;
        }
      } catch {
        showToast('❌ Network error', 'error');
        btn.textContent = '📨 Send Request'; btn.disabled = false;
      }
    });
  }



  /* ═══════════════════════════════════
     ADMIN PANEL
  ═══════════════════════════════════ */
  let _ap=1, _as='', _ar='', _aDebounce;

  /* ═══════════════════════════════════
     ADMIN PASSWORD CONFIRMATION
     Повертає Promise<boolean> — true якщо пароль підтверджено
  ═══════════════════════════════════ */

  // Дії що потребують підтвердження паролем
  const SENSITIVE_ACTIONS = {
    'role_change':       { label: 'Change user role',          icon: '👑' },
    'role_approve':      { label: 'Approve role request',      icon: '✅' },
    'role_reject':       { label: 'Reject role request',       icon: '❌' },
    'role_bulk':         { label: 'Bulk process role requests', icon: '📋' },
    'user_ban':          { label: 'Ban / deactivate user',     icon: '🚫' },
    'user_activate':     { label: 'Activate user',             icon: '🟢' },
    'user_delete':       { label: 'Delete user permanently',   icon: '🗑️' },
  };

  function requireAdminConfirm(actionKey, summaryHtml) {
    return new Promise(resolve => {
      const modal   = document.getElementById('adminConfirmModal');
      const label   = document.getElementById('confirmActionLabel');
      const summary = document.getElementById('confirmActionSummary');
      const pwdInp  = document.getElementById('confirmPassword');
      const errEl   = document.getElementById('confirmError');
      const submitBtn = document.getElementById('confirmSubmitBtn');
      const cancelBtn = document.getElementById('confirmCancelBtn');
      const toggleBtn = document.getElementById('confirmPassToggle');
      if (!modal) { resolve(false); return; }

      const meta = SENSITIVE_ACTIONS[actionKey] || { label: 'Sensitive action', icon: '🔐' };
      label.textContent   = `${meta.icon} ${meta.label}`;
      summary.innerHTML   = summaryHtml || 'This action cannot be undone.';
      pwdInp.value        = '';
      errEl.style.display = 'none';
      submitBtn.disabled  = false;
      submitBtn.textContent = '🔐 Confirm';
      modal.style.display = 'flex';
      setTimeout(() => pwdInp.focus(), 80);

      // Toggle password visibility
      const onToggle = () => {
        pwdInp.type = pwdInp.type === 'password' ? 'text' : 'password';
        toggleBtn.textContent = pwdInp.type === 'password' ? '👁' : '🙈';
      };

      const cleanup = (result) => {
        modal.style.display = 'none';
        submitBtn.removeEventListener('click', onSubmit);
        cancelBtn.removeEventListener('click', onCancel);
        toggleBtn.removeEventListener('click', onToggle);
        pwdInp.removeEventListener('keydown', onKeydown);
        resolve(result);
      };

      const onSubmit = async () => {
        const pwd = pwdInp.value.trim();
        if (!pwd) { pwdInp.focus(); return; }
        submitBtn.disabled = true;
        submitBtn.textContent = '⏳ Verifying…';
        errEl.style.display = 'none';
        try {
          const res = await NexusAuth.authFetch('/api/admin/verify-password', {
            method: 'POST', body: JSON.stringify({ password: pwd })
          });
          const d = await res?.json();
          if (d?.valid) {
            cleanup(true);
          } else {
            errEl.style.display = '';
            pwdInp.value = '';
            pwdInp.focus();
            submitBtn.disabled = false;
            submitBtn.textContent = '🔐 Confirm';
          }
        } catch {
          errEl.textContent = '⚠️ Network error. Try again.';
          errEl.style.display = '';
          submitBtn.disabled = false;
          submitBtn.textContent = '🔐 Confirm';
        }
      };

      const onCancel  = () => cleanup(false);
      const onKeydown = (e) => { if (e.key === 'Enter') onSubmit(); if (e.key === 'Escape') onCancel(); };

      submitBtn.addEventListener('click',  onSubmit);
      cancelBtn.addEventListener('click',  onCancel);
      toggleBtn.addEventListener('click',  onToggle);
      pwdInp.addEventListener('keydown',   onKeydown);

      // Click outside to cancel
      modal.addEventListener('click', e => { if (e.target === modal) onCancel(); }, { once: true });
    });
  }

  async function loadAdminData() {
    await Promise.all([loadAdminStats(), loadAdminUsers(), loadAuditLog(), loadRoleRequests()]);
    // Report download
    document.getElementById('downloadReportBtn')?.addEventListener('click', downloadReport);
    document.getElementById('downloadAnalyticsBtn')?.addEventListener('click', downloadAnalyticsReport);
  }

  async function loadAdminStats() {
    try {
      const res=await NexusAuth.authFetch('/api/admin/stats'); if(!res?.ok) return;
      const d=await res.json();
      _txt('asTotalUsers',d.total_users); _txt('asActiveUsers',d.active_users);
      _txt('asAdmins',d.by_role?.admin??0); _txt('asEditors',d.by_role?.editor??0);
      _txt('asViewers',d.by_role?.viewer??0); _txt('asAuditTotal',d.audit_total);
    } catch {}
  }

  async function loadAdminUsers(page=1) {
    _ap=page;
    const tbody=document.getElementById('adminUsersBody'); if(!tbody) return;
    tbody.innerHTML='<tr><td colspan="5" style="padding:20px;text-align:center;color:var(--text3)">Loading…</td></tr>';
    const p=new URLSearchParams({page,per_page:15});
    if(_as) p.set('search',_as); if(_ar) p.set('role',_ar);
    try {
      const res=await NexusAuth.authFetch('/api/admin/users?'+p); if(!res?.ok) return;
      const d=await res.json();
      if(!d.users.length){
        tbody.innerHTML='<tr><td colspan="5" style="padding:20px;text-align:center;color:var(--text3)">No users found</td></tr>';
        return;
      }
      const rc={admin:'#a78bfa',editor:'#ffa500',viewer:'#00ffc8'};
      tbody.innerHTML=d.users.map(u=>`
        <tr style="border-bottom:1px solid var(--border);transition:background .15s"
            onmouseover="this.style.background='var(--panel2)'" onmouseout="this.style.background=''">
          <td style="padding:10px 16px">
            <div style="font-weight:500;color:var(--text)">${esc(u.display_name)}</div>
            <div style="font-size:.72rem;color:var(--text3);font-family:var(--mono)">${esc(u.email)}</div>
          </td>
          <td style="padding:10px 16px">
            <span style="font-family:var(--mono);font-size:.72rem;padding:2px 8px;border-radius:99px;
              background:${rc[u.role]}22;border:1px solid ${rc[u.role]}55;color:${rc[u.role]}">${u.role}</span>
          </td>
          <td style="padding:10px 16px">
            <span style="font-family:var(--mono);font-size:.7rem;padding:2px 8px;border-radius:99px;
              background:${u.is_active?'rgba(0,255,200,.08)':'rgba(255,71,87,.08)'};
              border:1px solid ${u.is_active?'rgba(0,255,200,.2)':'rgba(255,71,87,.2)'};
              color:${u.is_active?'var(--accent)':'var(--danger)'}">${u.is_active?'active':'inactive'}</span>
          </td>
          <td style="padding:10px 16px;font-size:.75rem;color:var(--text2);font-family:var(--mono)">
            ${u.created_at?new Date(u.created_at).toLocaleDateString():'—'}
          </td>
          <td style="padding:10px 16px">
            <div style="display:flex;gap:6px">
              <select class="form-input role-select" data-uid="${u.id}" data-cur="${u.role}"
                style="padding:4px 6px;font-size:.72rem;width:80px">
                <option value="viewer" ${u.role==='viewer'?'selected':''}>viewer</option>
                <option value="editor" ${u.role==='editor'?'selected':''}>editor</option>
                <option value="admin"  ${u.role==='admin'?'selected':''}>admin</option>
              </select>
              <button class="toggle-status-btn" data-uid="${u.id}" data-active="${u.is_active}"
                style="padding:4px 10px;font-size:.7rem;border-radius:6px;cursor:pointer;
                  background:${u.is_active?'rgba(255,71,87,.12)':'rgba(0,255,200,.1)'};
                  border:1px solid ${u.is_active?'rgba(255,71,87,.3)':'rgba(0,255,200,.3)'};
                  color:${u.is_active?'var(--danger)':'var(--accent)'}">
                ${u.is_active?'Ban':'Activate'}</button>
            </div>
          </td>
        </tr>`).join('');

      tbody.querySelectorAll('.role-select').forEach(sel=>{
        sel.addEventListener('change', async()=>{
          const newRole = sel.value;
          const userName = sel.closest('tr')?.querySelector('td:first-child div')?.textContent || 'this user';
          const confirmed = await requireAdminConfirm('role_change',
            `Change role of <strong style="color:var(--text)">${esc(userName)}</strong><br>
             <span style="color:var(--accent)">${esc(sel.dataset.cur)}</span>
             <span style="margin:0 6px;color:var(--text3)">→</span>
             <span style="color:${newRole==='admin'?'#a78bfa':newRole==='editor'?'#ffa500':'var(--accent)'}">
               ${esc(newRole)}</span>`
          );
          if (!confirmed) { sel.value = sel.dataset.cur; return; }
          const res2=await NexusAuth.authFetch(`/api/admin/users/${sel.dataset.uid}/role`,
            {method:'PATCH',body:JSON.stringify({role:newRole})});
          if(res2?.ok){showToast(`✅ Role → ${newRole}`);sel.dataset.cur=newRole;}
          else{showToast('❌ Failed','error');sel.value=sel.dataset.cur;}
        });
      });
      tbody.querySelectorAll('.toggle-status-btn').forEach(btn=>{
        btn.addEventListener('click', async()=>{
          const isActive=btn.dataset.active==='true';
          const userName = btn.closest('tr')?.querySelector('td:first-child div')?.textContent || 'this user';
          const actionKey = isActive ? 'user_ban' : 'user_activate';
          const confirmed = await requireAdminConfirm(actionKey,
            `${isActive
              ? `<span style="color:var(--danger)">Ban</span> user <strong style="color:var(--text)">${esc(userName)}</strong><br>
                 <span style="font-size:.72rem;color:var(--text3)">User will lose access to the system.</span>`
              : `<span style="color:var(--accent)">Activate</span> user <strong style="color:var(--text)">${esc(userName)}</strong><br>
                 <span style="font-size:.72rem;color:var(--text3)">User will regain access to the system.</span>`
            }`
          );
          if (!confirmed) return;
          const res2=await NexusAuth.authFetch(`/api/admin/users/${btn.dataset.uid}/status`,
            {method:'PATCH',body:JSON.stringify({is_active:!isActive})});
          if(res2?.ok){showToast(`✅ User ${!isActive?'activated':'banned'}`);await loadAdminUsers(_ap);}
          else showToast('❌ Failed','error');
        });
      });

      _txt('adminPageInfo',`Page ${d.page} of ${d.pages} · ${d.total} users`);
      const prev=document.getElementById('adminPrevBtn');
      const next=document.getElementById('adminNextBtn');
      if(prev){prev.disabled=d.page<=1;    prev.onclick=()=>loadAdminUsers(d.page-1);}
      if(next){next.disabled=d.page>=d.pages; next.onclick=()=>loadAdminUsers(d.page+1);}
    } catch(e){console.error(e);}
  }

  let _auditActionF = '', _auditDateF = '';

  async function loadAuditLog() {
    const el=document.getElementById('auditLogList'); if(!el) return;
    try {
      const p = new URLSearchParams({per_page:50});
      if (_auditDateF) p.set('days', _auditDateF);
      const res=await NexusAuth.authFetch('/api/admin/audit?'+p); if(!res?.ok) return;
      const d=await res.json();
      const ac={
        'user.login':'var(--accent)','user.register':'var(--accent2)',
        'user.password_change':'var(--warn)','admin.role_change':'#a78bfa',
        'admin.user_delete':'var(--danger)','admin.user_deactivate':'var(--danger)',
        'file.upload':'#00b8ff','file.delete':'var(--danger)',
        'file.download':'var(--accent)','file.tag_add':'#ffa500',
        'file.tag_remove':'#ffa500','file.move':'#a78bfa',
      };

      let entries = d.entries || [];
      // Client-side filter by action text
      if (_auditActionF) {
        const q = _auditActionF.toLowerCase();
        entries = entries.filter(e => e.action.toLowerCase().includes(q) || (e.actor_name||'').toLowerCase().includes(q));
      }

      el.innerHTML = entries.length ? entries.map(e=>`
        <div style="display:flex;align-items:flex-start;gap:10px;padding:10px 16px;border-bottom:1px solid var(--border)">
          <div style="width:7px;height:7px;border-radius:50%;margin-top:5px;flex-shrink:0;
            background:${ac[e.action]||'var(--text3)'}"></div>
          <div style="flex:1">
            <span style="font-family:var(--mono);font-size:.72rem;color:${ac[e.action]||'var(--text2)'}">${esc(e.action)}</span>
            <span style="font-size:.75rem;color:var(--text2);margin-left:8px">by ${esc(e.actor_name)}</span>
            ${e.target_id?`<span style="font-size:.68rem;color:var(--text3);margin-left:6px">#${esc(e.target_id)}</span>`:''}
          </div>
          <span style="font-family:var(--mono);font-size:.65rem;color:var(--text3);flex-shrink:0">
            ${new Date(e.created_at).toLocaleString()}</span>
        </div>`).join('')
        : '<div style="padding:20px;text-align:center;color:var(--text3)">No matching entries</div>';

      // Wire up filters after first load
      document.getElementById('auditActionFilter')?.addEventListener('input', e=>{
        _auditActionF = e.target.value; loadAuditLog();
      });
      document.getElementById('auditDateFilter')?.addEventListener('change', e=>{
        _auditDateF = e.target.value; loadAuditLog();
      });
    } catch {}
  }

  async function downloadReport() {
    try {
      showToast('⏳ Generating report…');
      const [ur,ar,sr] = await Promise.all([
        NexusAuth.authFetch('/api/admin/users?per_page=100'),
        NexusAuth.authFetch('/api/admin/audit?per_page=100'),
        NexusAuth.authFetch('/api/admin/stats'),
      ]);
      const users = ur?.ok?(await ur.json()).users:[];
      const audit = ar?.ok?(await ar.json()).entries:[];
      const stats = sr?.ok?await sr.json():{};
      const now   = new Date().toLocaleString();
      let csv = `CYBER DATA NEXUS — Admin Report\nGenerated: ${now}\n\n`;
      csv += `=== SYSTEM STATS ===\nTotal Users,${stats.total_users||0}\nActive,${stats.active_users||0}\n`;
      csv += `Admins,${stats.by_role?.admin||0}\nEditors,${stats.by_role?.editor||0}\nViewers,${stats.by_role?.viewer||0}\n\n`;
      csv += `=== USERS ===\nID,Username,Email,Role,Status,Registered\n`;
      users.forEach(u=>csv+=`${u.id},"${u.username}","${u.email}",${u.role},${u.is_active?'active':'inactive'},"${u.created_at||''}"\n`);
      csv += `\n=== AUDIT LOG (last 100) ===\nTimestamp,Actor,Action,Target\n`;
      audit.forEach(e=>csv+=`"${e.created_at}","${e.actor_name}","${e.action}","${e.target_id||''}"\n`);
      const blob=new Blob([csv],{type:'text/csv;charset=utf-8;'});
      const a=Object.assign(document.createElement('a'),{href:URL.createObjectURL(blob),download:`nexus-report-${Date.now()}.csv`});
      a.click(); URL.revokeObjectURL(a.href);
      showToast('✅ Report downloaded');
    } catch(e){showToast('❌ Report failed','error');console.error(e);}
  }

  async function downloadAnalyticsReport() {
    try {
      showToast('⏳ Generating analytics report…');
      const res = await NexusAuth.authFetch('/api/admin/analytics-report');
      if (!res?.ok) { showToast('❌ Failed to generate report', 'error'); return; }
      const blob = await res.blob();
      const cd = res.headers.get('Content-Disposition') || '';
      const fnMatch = cd.match(/filename="([^"]+)"/);
      const filename = fnMatch ? fnMatch[1] : `nexus-analytics-${Date.now()}.csv`;
      const a = Object.assign(document.createElement('a'), {
        href: URL.createObjectURL(blob), download: filename
      });
      a.click(); URL.revokeObjectURL(a.href);
      showToast('✅ Analytics report downloaded');
    } catch(e) { showToast('❌ Report failed', 'error'); console.error(e); }
  }

  let _selectedReqIds = new Set();

  async function loadRoleRequests() {
    try {
      const res = await NexusAuth.authFetch('/api/admin/role-requests');
      if (!res?.ok) return;
      const d = await res.json();
      const list  = document.getElementById('roleRequestsList');
      const badge = document.getElementById('roleReqBadge');
      const bulkBar = document.getElementById('roleReqBulkBar');
      if (!list) return;

      _selectedReqIds.clear();

      if (badge) {
        if (d.total > 0) { badge.style.display = ''; badge.textContent = d.total; }
        else badge.style.display = 'none';
      }

      if (bulkBar) bulkBar.style.display = d.requests.length ? 'flex' : 'none';

      if (!d.requests.length) {
        list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text3);font-size:.8rem">No pending requests</div>';
        return;
      }

      const rc = {admin:'#a78bfa', editor:'#ffa500', viewer:'var(--accent)'};
      list.innerHTML = d.requests.map(r => `
        <div data-reqid="${r.id}" style="padding:12px 16px;border-bottom:1px solid var(--border);transition:background .15s"
          onmouseover="this.style.background='var(--panel2)'" onmouseout="this.style.background=''">
          <div style="display:flex;align-items:flex-start;gap:10px">
            <input type="checkbox" class="req-checkbox" data-id="${r.id}"
              style="margin-top:3px;flex-shrink:0;cursor:pointer;accent-color:var(--accent)">
            <div style="flex:1">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                <span style="font-size:.8rem;font-weight:500;color:var(--text)">${esc(r.display_name)}</span>
                <button class="view-user-btn" data-uid="${r.user_id}"
                  style="font-size:.68rem;padding:1px 8px;border-radius:99px;cursor:pointer;
                    background:rgba(0,184,255,.08);border:1px solid rgba(0,184,255,.25);color:#00b8ff">
                  👁 View Profile
                </button>
              </div>
              <div style="font-size:.7rem;color:var(--text3);font-family:var(--mono);margin-top:1px">${esc(r.email)}</div>
              <div style="margin-top:5px;font-size:.72rem;color:var(--text2)">
                <span style="color:var(--accent)">${esc(r.current_role)}</span>
                <span style="margin:0 5px;color:var(--text3)">→</span>
                <span style="color:${rc[r.requested_role]||'var(--text)'}">
                  ${esc(r.requested_role)}</span>
                <span style="margin-left:10px;color:var(--text3)">${new Date(r.created_at).toLocaleDateString()}</span>
              </div>
              ${r.message?`<div style="margin-top:5px;font-size:.72rem;color:var(--text2);font-style:italic;
                padding:5px 8px;background:rgba(255,255,255,.03);border-radius:5px;border-left:2px solid var(--border2)">
                "${esc(r.message)}"</div>`:''}
            </div>
          </div>
          <div style="display:flex;gap:6px;margin-top:10px;margin-left:22px">
            <button class="req-approve-btn" data-id="${r.id}"
              style="flex:1;padding:5px;font-size:.72rem;border-radius:6px;cursor:pointer;
                background:rgba(0,255,200,.1);border:1px solid rgba(0,255,200,.3);color:var(--accent)">
              ✅ Approve
            </button>
            <button class="req-reject-btn" data-id="${r.id}"
              style="flex:1;padding:5px;font-size:.72rem;border-radius:6px;cursor:pointer;
                background:rgba(255,71,87,.08);border:1px solid rgba(255,71,87,.3);color:var(--danger)">
              ❌ Reject
            </button>
          </div>
        </div>`).join('');

      // Checkboxes
      list.querySelectorAll('.req-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
          if (cb.checked) _selectedReqIds.add(cb.dataset.id);
          else _selectedReqIds.delete(cb.dataset.id);
          updateReqSelCount();
        });
      });

      // Select all
      document.getElementById('roleReqSelectAll')?.addEventListener('change', e => {
        list.querySelectorAll('.req-checkbox').forEach(cb => {
          cb.checked = e.target.checked;
          if (e.target.checked) _selectedReqIds.add(cb.dataset.id);
          else _selectedReqIds.delete(cb.dataset.id);
        });
        updateReqSelCount();
      });

      // Bulk approve/reject — only wire once
      const bApprove = document.getElementById('bulkApproveBtn');
      const bReject  = document.getElementById('bulkRejectBtn');
      if (bApprove) bApprove.onclick = () => bulkRoleReqAction('approve');
      if (bReject)  bReject.onclick  = () => bulkRoleReqAction('reject');

      // Individual approve/reject
      list.querySelectorAll('.req-approve-btn').forEach(btn =>
        btn.addEventListener('click', () => handleRoleReqAction(btn.dataset.id, 'approve')));
      list.querySelectorAll('.req-reject-btn').forEach(btn =>
        btn.addEventListener('click', () => handleRoleReqAction(btn.dataset.id, 'reject')));

      // View user profile
      list.querySelectorAll('.view-user-btn').forEach(btn =>
        btn.addEventListener('click', () => showUserProfileModal(btn.dataset.uid)));

    } catch(e) { console.error(e); }
  }

  function updateReqSelCount() {
    const el = document.getElementById('roleReqSelCount');
    if (el) el.textContent = _selectedReqIds.size ? `${_selectedReqIds.size} selected` : '';
  }

  async function bulkRoleReqAction(action) {
    if (!_selectedReqIds.size) { showToast('⚠️ Select at least one request', 'error'); return; }
    const ids = [..._selectedReqIds].map(Number);

    const confirmed = await requireAdminConfirm('role_bulk',
      `${action === 'approve' ? '✅ Approve' : '❌ Reject'}
       <strong style="color:var(--text)">${ids.length} role request(s)</strong><br>
       <span style="font-size:.72rem;color:var(--text3)">This will affect all selected users at once.</span>`
    );
    if (!confirmed) return;

    try {
      const res = await NexusAuth.authFetch('/api/admin/role-requests/bulk', {
        method: 'PATCH', body: JSON.stringify({ action, ids })
      });
      const d = await res?.json();
      const count = d?.updated || 0;
      showToast(action === 'approve' ? `✅ ${count} request(s) approved` : `🚫 ${count} request(s) rejected`);
      await loadRoleRequests();
      await loadAdminUsers();
    } catch { showToast('❌ Network error', 'error'); }
  }

  async function showUserProfileModal(uid) {
    const modal = document.getElementById('userProfileModal');
    const body  = document.getElementById('userModalBody');
    if (!modal || !body) return;
    modal.style.display = 'flex';
    body.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text3)">⏳ Loading…</div>';

    document.getElementById('closeUserModal')?.addEventListener('click', () => {
      modal.style.display = 'none';
    }, {once: true});
    modal.addEventListener('click', e => {
      if (e.target === modal) modal.style.display = 'none';
    }, {once: true});

    try {
      const res = await NexusAuth.authFetch(`/api/admin/users/${uid}/profile`);
      if (!res?.ok) { body.innerHTML = '<div style="padding:20px;color:var(--danger)">Failed to load user</div>'; return; }
      const u = await res.json();
      const rc = {admin:'#a78bfa', editor:'#ffa500', viewer:'#00ffc8'};
      const fmt = b => !b?'0 B':b>1e9?(b/1e9).toFixed(1)+' GB':b>1e6?(b/1e6).toFixed(0)+' MB':(b/1024).toFixed(0)+' KB';
      body.innerHTML = `
        <div style="display:flex;align-items:center;gap:14px;margin-bottom:20px">
          <div style="width:52px;height:52px;border-radius:50%;background:linear-gradient(135deg,#7c3aed,#00b8ff);
            display:flex;align-items:center;justify-content:center;font-size:1.4rem;flex-shrink:0">👤</div>
          <div>
            <div style="font-size:1rem;font-weight:600;color:var(--text)">${esc(u.display_name)}</div>
            <div style="font-size:.75rem;color:var(--text3);font-family:var(--mono)">@${esc(u.username)}</div>
            <div style="margin-top:4px">
              <span style="font-family:var(--mono);font-size:.7rem;padding:2px 8px;border-radius:99px;
                background:${rc[u.role]}22;border:1px solid ${rc[u.role]}55;color:${rc[u.role]}">${u.role}</span>
              ${u.is_verified?'<span style="margin-left:6px;font-size:.7rem;color:var(--accent)">✓ Verified</span>':''}
            </div>
          </div>
        </div>
        <div style="display:grid;gap:10px">
          ${[
            ['📧 Email',    u.email],
            ['📱 Phone',    u.phone || '—'],
            ['📍 Location', u.location || '—'],
            ['🌐 Language', u.language || '—'],
            ['🕒 Timezone', u.timezone || '—'],
            ['📅 Registered', u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'],
            ['🕐 Last Login', u.last_login_at ? new Date(u.last_login_at).toLocaleString() : 'Never'],
            ['📊 Status', u.is_active ? '🟢 Active' : '🔴 Inactive'],
          ].map(([l,v])=>`
            <div style="display:flex;justify-content:space-between;align-items:center;
              padding:8px 0;border-bottom:1px solid var(--border)">
              <span style="font-size:.78rem;color:var(--text3)">${l}</span>
              <span style="font-size:.8rem;color:var(--text2);font-family:var(--mono)">${esc(String(v))}</span>
            </div>`).join('')}
          ${u.bio?`<div style="padding:10px;background:rgba(255,255,255,.03);border-radius:8px;
            font-size:.78rem;color:var(--text2);font-style:italic">"${esc(u.bio)}"</div>`:''}
        </div>`;
    } catch(e) {
      body.innerHTML = '<div style="padding:20px;color:var(--danger)">Error loading profile</div>';
    }
  }

  async function handleRoleReqAction(id, action) {
    // Знаходимо інфо про запит з DOM для summary
    const card = document.querySelector(`[data-reqid="${id}"]`);
    const name = card?.querySelector('span[style*="font-weight"]')?.textContent || 'user';
    const roleArrow = card?.querySelector('div[style*="font-size:.72rem"]')?.textContent?.trim() || '';

    const confirmed = await requireAdminConfirm(
      action === 'approve' ? 'role_approve' : 'role_reject',
      `${action === 'approve' ? '✅ Approve' : '❌ Reject'} role request from
       <strong style="color:var(--text)">${esc(name)}</strong><br>
       <span style="font-size:.72rem;color:var(--text3)">${esc(roleArrow)}</span>`
    );
    if (!confirmed) return;

    try {
      const res = await NexusAuth.authFetch(`/api/admin/role-requests/${id}`, {
        method: 'PATCH', body: JSON.stringify({ action })
      });
      if (res?.ok) {
        showToast(action === 'approve' ? '✅ Role upgraded!' : '🚫 Request rejected');
        await loadRoleRequests();
        await loadAdminUsers();
      } else showToast('❌ Failed', 'error');
    } catch { showToast('❌ Network error', 'error'); }
  }

  /* ═══════════════════════════════════
     UTILITIES
  ═══════════════════════════════════ */

  document.getElementById('adminUserSearch')?.addEventListener('input',e=>{
    clearTimeout(_aDebounce);
    _aDebounce=setTimeout(()=>{_as=e.target.value;loadAdminUsers(1);},350);
  });
  document.getElementById('adminRoleFilter')?.addEventListener('change',e=>{_ar=e.target.value;loadAdminUsers(1);});
  document.querySelector('[data-pane=admin]')?.addEventListener('click',loadAdminData);
  function _txt(id,val){ const el=document.getElementById(id); if(el) el.textContent=val; }
  function esc(s){ return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

  function showToast(msg,type='success'){
    const color=type==='error'?'#ff4757':'var(--accent)';
    const el=document.createElement('div');
    el.textContent=msg;
    el.style.cssText=`position:fixed;bottom:24px;right:24px;z-index:9999;
      background:var(--panel);border:1px solid var(--border2);border-left:3px solid ${color};
      color:var(--text);font-family:var(--mono);font-size:.8rem;padding:12px 20px;
      border-radius:var(--r2);box-shadow:0 8px 32px rgba(0,0,0,.4);animation:toastIn .3s ease`;
    document.head.insertAdjacentHTML('beforeend',
      '<style>@keyframes toastIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}</style>');
    document.body.appendChild(el);
    setTimeout(()=>{el.style.transition='opacity .3s';el.style.opacity='0';setTimeout(()=>el.remove(),300);},2800);
  }
  window.nexusToast = showToast;

}); // DOMContentLoaded