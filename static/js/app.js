// CYBERPUNK DATA NEXUS - Frontend Logic

console.log('🚀 App.js loading...');

class CyberDataNexus {
    constructor() {
        console.log('🎯 CyberDataNexus constructor called');
        this.currentCategory = 'all';
        this.currentSubcategory = null;
        this.searchQuery = '';
        this.searchCategoryFilter = null; // фільтр по категорії всередині результатів пошуку
        this.selectedFileId = null;
        this.files = [];

        // Bulk selection state
        this.bulkMode = false;
        this.selectedFileIds = new Set();

        this.init();
    }

    init() {
        console.log('⚙️ Initializing app...');
        this.setupEventListeners();
        this.loadCategoryTabs();   // динамічна відмальовка tabs з API
        this.loadFiles();
        this.updateStats();

        // Ініціалізуємо панель деталей як закриту
        this.closeDetailsPanel();
        // Деактивуємо menu-кнопки File при старті (нічого не вибрано)
        this.updateMenuFileButtons();
        // Smart Alerts — завантажуємо при старті
        this.alertsLoad();
        // Обмеження UI по ролі (передається з Flask через window.__NEXUS_ROLE__)
        this.applyRoleRestrictions();
        console.log('✅ App initialized successfully');
    }

    applyRoleRestrictions() {
        const role = window.__NEXUS_ROLE__ || 'viewer';
        if (role === 'viewer') {
            // Viewer не може завантажувати, видаляти, редагувати теги, керувати категоріями
            const editorOnlyIds = [
                'uploadBtn', 'menuUploadBtn',
                'menuAddTagBtn', 'menuRemoveTagBtn', 'menuMoveBtn',
                'menuManageCategories', 'menuDeleteSelected',
                'bulkTagBtn', 'bulkRemoveTagBtn', 'bulkMoveBtn', 'bulkDeleteBtn',
            ];
            editorOnlyIds.forEach(id => {
                const el = document.getElementById(id);
                if (!el) return;
                el.disabled = true;
                el.style.opacity = '0.35';
                el.style.cursor  = 'not-allowed';
                el.style.pointerEvents = 'none';
                el.title = 'Requires Editor role or higher';
            });
            // Bulk Select — viewer може вибирати тільки для Download, але Edit/Manage — ні
            // Ховаємо Edit і Manage пункти меню повністю
            const menuEdit   = document.querySelector('.menu-item:has(#menuAddTagBtn)');
            const menuManage = document.querySelector('.menu-item:has(#menuManageCategories)');
            if (menuEdit)   { menuEdit.style.opacity='0.35'; menuEdit.style.pointerEvents='none'; }
            if (menuManage) { menuManage.style.opacity='0.35'; menuManage.style.pointerEvents='none'; }
        }
    }

    async loadCategoryTabs() {
        // Базові категорії з іконками
        const baseLabels = {
            'all':      'All',
            'document': '📄 Documents',
            'code':     '💻 Code',
            'image':    '🖼️ Images',
            'video':    '🎥 Video',
            'audio':    '🎵 Audio',
            'archive':  '📦 Archives',
            'other':    '📌 Other',
        };

        // Отримуємо всі категорії з API (включно з кастомними)
        let apiCats = [];
        try {
            const res = await fetch('/api/categories');
            if (res.ok) apiCats = await res.json();
        } catch(e) { console.error('loadCategoryTabs error', e); }

        // Будуємо повний список: All + базові + кастомні
        const tabs = [
            { id: 'all', label: 'All' },
            ...apiCats.map(cat => ({
                id: cat.id,
                label: baseLabels[cat.id] || `🗂️ ${cat.id.charAt(0).toUpperCase() + cat.id.slice(1)}`
            }))
        ];

        const container = document.getElementById('categoryTabs');
        const currentCat = this.currentCategory || 'all';

        container.innerHTML = tabs.map(tab => `
            <button class="cat-tab${tab.id === currentCat ? ' active' : ''}" data-category="${tab.id}">
                ${tab.label}
            </button>
        `).join('');

        // Прив'язуємо обробники
        container.querySelectorAll('.cat-tab[data-category]').forEach(btn => {
            btn.addEventListener('click', (e) => this.setCategory(e.currentTarget.dataset.category));
        });
    }

    setupEventListeners() {
        const fileInput = document.getElementById('fileInput');

        // Upload
        document.getElementById('uploadBtn').addEventListener('click', () => fileInput.click());
        document.getElementById('menuUploadBtn').addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', (e) => this.handleFileSelect(e));

        // Drag & Drop onto window
        document.body.addEventListener('dragover', (e) => e.preventDefault());
        document.body.addEventListener('drop', (e) => { e.preventDefault(); this.handleFileSelect(e); });

        // Search
        const searchInput = document.getElementById('searchInput');
        const searchClearBtn = document.getElementById('searchClearBtn');

        searchInput.addEventListener('input', (e) => {
            this.searchQuery = e.target.value.trim();
            this.searchCategoryFilter = null;
            this.loadFiles();
            // Показуємо/ховаємо кнопку очищення
            if (searchClearBtn) searchClearBtn.style.display = this.searchQuery ? 'flex' : 'none';
        });
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this._clearSearch();
            }
        });
        if (searchClearBtn) {
            searchClearBtn.style.display = 'none';
            searchClearBtn.addEventListener('click', () => this._clearSearch());
        }

        // Category tabs
        document.querySelectorAll('.cat-tab[data-category]').forEach(btn => {
            btn.addEventListener('click', (e) => this.setCategory(e.currentTarget.dataset.category));
        });

        // Details panel
        document.getElementById('closeDetailsBtn').addEventListener('click', () => this.closeDetailsPanel());
        document.getElementById('detailsOverlay').addEventListener('click', () => this.closeDetailsPanel());

        // Bulk toolbar
        document.getElementById('bulkToggleBtn').addEventListener('click', () => this.enableBulkMode());
        document.getElementById('bulkCancelBtn').addEventListener('click', () => this.disableBulkMode());
        document.getElementById('bulkDeleteBtn').addEventListener('click', () => this.bulkDelete());
        document.getElementById('bulkDownloadBtn').addEventListener('click', () => this.bulkDownload());
        document.getElementById('bulkTagBtn').addEventListener('click', () => this.bulkAddTag());
        document.getElementById('bulkMoveBtn').addEventListener('click', () => this.bulkMoveCategory());
        document.getElementById('bulkRemoveTagBtn').addEventListener('click', () => this.bulkRemoveTag());
        document.getElementById('selectAllCheckbox').addEventListener('change', (e) => {
            if (e.target.checked) this.files.forEach(f => this.selectedFileIds.add(f.file_id));
            else this.selectedFileIds.clear();
            this.renderFiles();
            this.updateBulkToolbar();
        });

        // Menu: File
        document.getElementById('menuSelectBtn').addEventListener('click', () => { this.enableBulkMode(); this.closeAllMenus(); });
        document.getElementById('menuDownloadSelected').addEventListener('click', () => { this.menuDownload(); this.closeAllMenus(); });
        document.getElementById('menuDeleteSelected').addEventListener('click', () => { this.menuDelete(); this.closeAllMenus(); });

        // Menu: Edit — вмикає bulk-режим автоматично
        document.getElementById('menuAddTagBtn').addEventListener('click', () => {
            this.closeAllMenus();
            if (!this.bulkMode) this.enableBulkMode();
            if (this.selectedFileIds.size > 0) this.bulkAddTag();
            else this.showToast('Виберіть файли, потім Edit → Add Tag', 'info');
        });
        document.getElementById('menuRemoveTagBtn').addEventListener('click', () => {
            this.closeAllMenus();
            if (!this.bulkMode) this.enableBulkMode();
            if (this.selectedFileIds.size > 0) this.bulkRemoveTag();
            else this.showToast('Виберіть файли, потім Edit → Remove Tag', 'info');
        });
        document.getElementById('menuMoveBtn').addEventListener('click', () => {
            this.closeAllMenus();
            if (!this.bulkMode) this.enableBulkMode();
            if (this.selectedFileIds.size > 0) this.bulkMoveCategory();
            else this.showToast('Виберіть файли, потім Edit → Move', 'info');
        });

        // Menu: View
        document.querySelectorAll('.view-mode-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const mode = e.currentTarget.dataset.view;
                document.getElementById('filesGrid').classList.toggle('list-view', mode === 'list');
                document.querySelectorAll('.view-mode-btn').forEach(b => b.classList.remove('active-view'));
                e.currentTarget.classList.add('active-view');
                this.closeAllMenus();
            });
        });

        // Zoom
        this.zoomLevel = 100;
        document.getElementById('zoomIn').addEventListener('click', () => this.changeZoom(10));
        document.getElementById('zoomOut').addEventListener('click', () => this.changeZoom(-10));
        document.getElementById('zoomReset').addEventListener('click', () => this.setZoom(100));
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey || e.metaKey) {
                if (e.key === '=' || e.key === '+') { e.preventDefault(); this.changeZoom(10); }
                if (e.key === '-') { e.preventDefault(); this.changeZoom(-10); }
                if (e.key === '0') { e.preventDefault(); this.setZoom(100); }
            }
        });

        // Menu: Manage
        document.getElementById('menuManageCategories').addEventListener('click', () => { this.closeAllMenus(); this.manageCategoriesDialog(); });

        // Menu: Help
        document.getElementById('menuAbout').addEventListener('click', () => {
            this.showToast('⚡ CYBER DATA NEXUS v2.077 — AI-Powered File Management', 'info');
        });

        // Menu: Analytics
        const analyticsBtn = document.getElementById('menuAnalytics');
        if (analyticsBtn) {
            analyticsBtn.addEventListener('click', () => { this.closeAllMenus(); this.showAnalytics(); });
        }

        // Bell button — Smart Alerts
        const bellBtn = document.getElementById('alertsBellBtn');
        if (bellBtn) bellBtn.addEventListener('click', () => this.alertsOpen());

        // Menu dropdown click-to-open
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.menu-item'))
                document.querySelectorAll('.menu-item').forEach(m => m.classList.remove('open'));
        });
        document.querySelectorAll('.menu-item').forEach(item => {
            item.querySelector('.menu-item-label').addEventListener('click', (e) => {
                e.stopPropagation();
                const wasOpen = item.classList.contains('open');
                document.querySelectorAll('.menu-item').forEach(m => m.classList.remove('open'));
                if (!wasOpen) item.classList.add('open');
            });
            // Зупиняємо бульбашіння для всіх кнопок всередині dropdown —
            // інакше document click закриває меню до того як кнопка отримає клік.
            // Після дії явно закриваємо меню через closeAllMenus().
            const dropdown = item.querySelector('.menu-dropdown');
            if (dropdown) {
                dropdown.addEventListener('click', (e) => e.stopPropagation());
            }
        });
    }

    changeZoom(delta) { this.setZoom((this.zoomLevel || 100) + delta); }
    setZoom(level) {
        this.zoomLevel = Math.min(150, Math.max(70, level));
        document.documentElement.style.setProperty('--zoom', this.zoomLevel / 100);
        document.getElementById('zoomValue').textContent = this.zoomLevel + '%';
    }

    closeAllMenus() {
        document.querySelectorAll('.menu-item').forEach(m => m.classList.remove('open'));
    }

    _clearSearch() {
        const input = document.getElementById('searchInput');
        const btn   = document.getElementById('searchClearBtn');
        if (input) input.value = '';
        if (btn)   btn.style.display = 'none';
        this.searchQuery = '';
        this.searchCategoryFilter = null;
        this._searchMeta = null;
        this.loadFiles();
    }

    async handleFileSelect(e) {
        const files = e.target.files || e.dataTransfer.files;
        if (!files.length) return;

        this.showLoading();

        for (let file of files) {
            await this.uploadFile(file);
        }

        this.hideLoading();
        this.loadFiles();
        this.updateStats();

        // Очищуємо input для можливості завантажити той самий файл знову
        const fileInput = document.getElementById('fileInput');
        if (fileInput) {
            fileInput.value = '';
        }
    }

    async uploadFile(file, replaceExisting = false) {
        const formData = new FormData();
        formData.append('file', file);

        if (replaceExisting) {
            formData.append('replace', 'true');
        }

        try {
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (response.status === 409 && data.duplicate) {
                // Файл вже існує - показуємо діалог
                return await this.handleDuplicateFile(file, data.existing_file);
            }

            if (!response.ok) {
                throw new Error(data.error || 'Upload failed');
            }

            console.log('File uploaded:', data);
            return true;
        } catch (error) {
            console.error('Error uploading file:', error);
            alert('Error uploading file: ' + error.message);
            return false;
        }
    }

    async handleDuplicateFile(file, existingFile) {
        // Обробляє дублікат файлу - показує діалог користувачу
        const fileName = file.name;

        // Показуємо модальне вікно з опціями
        const action = await this.showDuplicateDialog(fileName, existingFile);

        if (action === 'cancel') {
            return false;
        }

        if (action === 'replace') {
            // Заміняємо існуючий файл
            return await this.uploadFile(file, true);
        }

        if (action === 'rename') {
            // Показуємо діалог для введення нової назви
            const newName = await this.showRenameDialog(fileName);

            if (!newName || newName === fileName) {
                // Користувач скасував або не змінив назву
                return false;
            }

            // Створюємо новий File об'єкт з новою назвою
            const renamedFile = new File([file], newName, { type: file.type });
            return await this.uploadFile(renamedFile, false);
        }

        return false;
    }

    async showRenameDialog(currentFileName) {
        // Показує діалог для введення нової назви файлу
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'duplicate-dialog-overlay';

            const dialog = document.createElement('div');
            dialog.className = 'duplicate-dialog';

            // Розділяємо назву на базу та розширення
            const lastDot = currentFileName.lastIndexOf('.');
            const hasExt = lastDot > 0 && lastDot < currentFileName.length - 1;
            const baseName = hasExt ? currentFileName.slice(0, lastDot) : currentFileName;
            const originalExt = hasExt ? currentFileName.slice(lastDot + 1) : '';

            // Популярні розширення згруповані
            const commonExtensions = [
                // Documents
                'pdf', 'doc', 'docx', 'txt', 'odt', 'rtf', 'md',
                // Spreadsheets
                'xls', 'xlsx', 'csv', 'ods',
                // Presentations
                'ppt', 'pptx', 'odp',
                // Code
                'js', 'ts', 'py', 'java', 'cpp', 'c', 'cs', 'go', 'rb', 'php',
                'html', 'css', 'scss', 'json', 'xml', 'yaml', 'yml', 'sh', 'sql',
                // Images
                'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp', 'ico',
                // Video
                'mp4', 'avi', 'mkv', 'mov', 'webm',
                // Audio
                'mp3', 'wav', 'ogg', 'flac', 'm4a',
                // Archives
                'zip', 'rar', '7z', 'tar', 'gz',
            ];

            // Якщо оригінальне розширення не в списку — додаємо його першим
            const extSet = new Set(commonExtensions.map(e => e.toLowerCase()));
            const orderedExts = originalExt && !extSet.has(originalExt.toLowerCase())
                ? [originalExt, ...commonExtensions]
                : commonExtensions;

            const optionsHtml = orderedExts.map(e =>
                `<option value="${e}" ${e.toLowerCase() === originalExt.toLowerCase() ? 'selected' : ''}>.${e}</option>`
            ).join('');

            dialog.innerHTML = `
                <div class="duplicate-dialog-header">
                    <h3>📝 Введіть нову назву файлу</h3>
                </div>
                <div class="duplicate-dialog-content">
                    <p class="duplicate-warning">
                        Поточна назва: <strong>"${currentFileName}"</strong>
                    </p>
                    <div class="rename-input-container">
                        <label class="rename-label">Нова назва файлу:</label>
                        <div class="rename-input-group">
                            <input type="text"
                                   class="rename-input"
                                   id="renameInput"
                                   value="${baseName}"
                                   placeholder="Введіть назву...">
                            <select class="rename-ext-select" id="renameExtSelect">
                                ${optionsHtml}
                            </select>
                        </div>
                        <p class="rename-hint">💡 AI класифікатор працює краще з осмисленими назвами</p>
                    </div>
                </div>
                <div class="duplicate-dialog-actions">
                    <button class="dialog-btn btn-cancel" data-action="cancel">
                        ❌ Скасувати
                    </button>
                    <button class="dialog-btn btn-primary" data-action="save">
                        ✅ Зберегти
                    </button>
                </div>
            `;

            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            const input = dialog.querySelector('#renameInput');
            const extSelect = dialog.querySelector('#renameExtSelect');
            input.focus();
            input.select();

            const saveBtn = dialog.querySelector('[data-action="save"]');
            const cancelBtn = dialog.querySelector('[data-action="cancel"]');

            const handleSave = () => {
                const newBaseName = input.value.trim();
                if (!newBaseName) {
                    input.classList.add('error-shake');
                    setTimeout(() => input.classList.remove('error-shake'), 500);
                    return;
                }
                const chosenExt = extSelect.value;
                const newFileName = chosenExt ? `${newBaseName}.${chosenExt}` : newBaseName;
                document.body.removeChild(overlay);
                resolve(newFileName);
            };

            const handleCancel = () => {
                document.body.removeChild(overlay);
                resolve(null);
            };

            saveBtn.addEventListener('click', handleSave);
            cancelBtn.addEventListener('click', handleCancel);
            input.addEventListener('keypress', (e) => { if (e.key === 'Enter') handleSave(); });
            input.addEventListener('keydown', (e) => { if (e.key === 'Escape') handleCancel(); });
            overlay.addEventListener('click', (e) => { if (e.target === overlay) handleCancel(); });
        });
    }

    async showDuplicateDialog(fileName, existingFile) {
        // Показує діалог з опціями для дублікату
        return new Promise((resolve) => {
            // Створюємо overlay
            const overlay = document.createElement('div');
            overlay.className = 'duplicate-dialog-overlay';

            // Створюємо діалог
            const dialog = document.createElement('div');
            dialog.className = 'duplicate-dialog';

            // Форматуємо інформацію про існуючий файл
            const categoryLabel = this.getCategoryLabel(existingFile.category);
            const subcategoryLabel = existingFile.subcategory.toUpperCase();
            const uploadDate = this.formatDate(existingFile.upload_date);

            dialog.innerHTML = `
                <div class="duplicate-dialog-header">
                    <h3>⚠️ Файл вже існує</h3>
                </div>
                <div class="duplicate-dialog-content">
                    <p class="duplicate-warning">
                        Файл <strong>"${fileName}"</strong> вже завантажено в систему
                    </p>
                    <div class="existing-file-info">
                        <div class="info-row">
                            <span class="info-label">📂 Категорія:</span>
                            <span class="info-value">${categoryLabel}</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">🗂️ Підкатегорія:</span>
                            <span class="info-value">${subcategoryLabel}</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">📅 Завантажено:</span>
                            <span class="info-value">${uploadDate}</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">💾 Розмір:</span>
                            <span class="info-value">${this.formatSize(existingFile.size)}</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">🏷️ Теги:</span>
                            <span class="info-value">${existingFile.tags.join(', ')}</span>
                        </div>
                    </div>
                    <p class="duplicate-question">Що ви хочете зробити?</p>
                </div>
                <div class="duplicate-dialog-actions">
                    <button class="dialog-btn btn-cancel" data-action="cancel">
                        ❌ Скасувати
                    </button>
                    <button class="dialog-btn btn-rename" data-action="rename">
                        📝 Зберегти з новою назвою
                    </button>
                    <button class="dialog-btn btn-replace" data-action="replace">
                        🔄 Замінити існуючий
                    </button>
                </div>
            `;

            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            // Обробники кнопок
            const buttons = dialog.querySelectorAll('.dialog-btn');
            buttons.forEach(btn => {
                btn.addEventListener('click', () => {
                    const action = btn.dataset.action;
                    document.body.removeChild(overlay);
                    resolve(action);
                });
            });

            // Закриття по кліку на overlay
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    document.body.removeChild(overlay);
                    resolve('cancel');
                }
            });
        });
    }

    getCategoryLabel(category) {
        const labels = {
            'document': '📄 DOCUMENTS',
            'code': '💻 CODE',
            'image': '🖼️ IMAGES',
            'video': '🎥 VIDEO',
            'audio': '🎵 AUDIO',
            'archive': '📦 ARCHIVES',
            'other': '📌 OTHER'
        };
        return labels[category] || category.toUpperCase();
    }

    setCategory(category) {
        this.currentCategory = category;
        this.currentSubcategory = null;

        document.querySelectorAll('.cat-tab[data-category]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.category === category);
        });

        this.loadFiles();
        this.loadSubcategories(category);
    }

    async loadSubcategories(category) {
        const subcategoriesBar = document.getElementById('subcategoriesBar');
        const subcategoryButtons = document.getElementById('subcategoryButtons');

        if (category === 'all') {
            subcategoriesBar.style.display = 'none';
            return;
        }

        try {
            // Новий endpoint — повертає системні + кастомні підкатегорії
            const response = await fetch(`/api/categories/${category}/subcategories`);
            const subcategories = await response.json();

            // Показуємо bar якщо є хоча б одна підкатегорія (крім general)
            // або якщо є кастомні — навіть порожні списки для кастомних категорій
            const hasSubs = subcategories.length > 0;

            if (hasSubs) {
                subcategoriesBar.style.display = 'flex';
                subcategoryButtons.innerHTML = '';
                subcategories.forEach((sub, index) => {
                    const btn = document.createElement('button');
                    btn.className = 'cat-tab';
                    if (index === 0) btn.classList.add('active');
                    btn.textContent = sub === 'general' ? 'All' : sub.charAt(0).toUpperCase() + sub.slice(1);
                    btn.addEventListener('click', () => {
                        this.currentSubcategory = sub === 'general' ? null : sub;
                        this.loadFiles();
                        document.querySelectorAll('#subcategoryButtons .cat-tab').forEach(b => b.classList.remove('active'));
                        btn.classList.add('active');
                    });
                    subcategoryButtons.appendChild(btn);
                });
            } else {
                subcategoriesBar.style.display = 'none';
            }
        } catch (error) {
            console.error('Error loading subcategories:', error);
            subcategoriesBar.style.display = 'none';
        }
    }

    async loadFiles() {
        try {
            if (this.searchQuery) {
                // ── Глобальний пошук: шукаємо по всіх категоріях ──
                const params = new URLSearchParams({ q: this.searchQuery });
                const response = await fetch('/api/search?' + params.toString());
                const data = await response.json();

                // Зберігаємо ПОВНИЙ список окремо — він не змінюється при фільтрації
                this._searchMeta = data;
                this._searchAllResults = data.results || [];

                // this.files = те що показуємо (може бути відфільтровано по категорії)
                this.files = this.searchCategoryFilter
                    ? this._searchAllResults.filter(f => f.category === this.searchCategoryFilter)
                    : this._searchAllResults;
            } else {
                // ── Звичайний перегляд: з урахуванням категорії/підкатегорії ──
                this._searchMeta = null;
                this._searchAllResults = null;
                const params = new URLSearchParams();
                if (this.currentCategory !== 'all') params.append('category', this.currentCategory);
                if (this.currentSubcategory) params.append('subcategory', this.currentSubcategory);
                const response = await fetch('/api/files?' + params.toString());
                this.files = await response.json();
            }

            this.renderFiles();
        } catch (error) {
            console.error('Error loading files:', error);
        }
    }

    renderFiles() {
        const filesGrid = document.getElementById('filesGrid');
        const fileCount = document.getElementById('fileCount');

        filesGrid.innerHTML = '';
        fileCount.textContent = `${this.files.length} files`;

        // ── Якщо є активний пошук — показуємо панель фільтрів по категоріях ──
        if (this.searchQuery && this._searchMeta) {
            const searchBar = this._buildSearchFilterBar(this._searchMeta);
            filesGrid.appendChild(searchBar);
        }

        if (this.files.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.innerHTML = this.searchQuery
                ? `<div class="empty-state-icon">🔍</div>
                   <p class="empty-state-text">Нічого не знайдено за запитом <strong>"${this.escapeHtml(this.searchQuery)}"</strong></p>
                   <p class="empty-state-hint">Спробуйте інше слово або очистіть пошук (Escape)</p>`
                : `<div class="empty-state-icon">📂</div>
                   <p class="empty-state-text">No files found</p>`;
            filesGrid.appendChild(empty);
            return;
        }

        this.files.forEach(file => {
            const card = this.createFileCard(file);
            filesGrid.appendChild(card);
        });
    }

    _buildSearchFilterBar(meta) {
        const bar = document.createElement('div');
        bar.className = 'search-filter-bar';

        const icons = {
            document: '📄', code: '💻', image: '🖼️',
            video: '🎥', audio: '🎵', archive: '📦', other: '📌'
        };

        // Лічильники завжди беремо з повного списку результатів
        const allResults = this._searchAllResults || [];
        const total = allResults.length;

        // Підраховуємо by_category з повного списку (не з meta, бо вона не змінюється при фільтрі)
        const byCategory = {};
        allResults.forEach(f => { byCategory[f.category] = (byCategory[f.category] || 0) + 1; });

        const applyFilter = (cat) => {
            this.searchCategoryFilter = cat;
            // Фільтруємо з повного списку — не з поточного this.files
            this.files = cat
                ? allResults.filter(f => f.category === cat)
                : allResults;
            this.renderFiles();
        };

        // Кнопка "Всі"
        const allBtn = document.createElement('button');
        allBtn.className = 'search-filter-btn' + (this.searchCategoryFilter === null ? ' active' : '');
        allBtn.innerHTML = `🔍 Всі <span class="search-filter-count">${total}</span>`;
        allBtn.addEventListener('click', () => applyFilter(null));
        bar.appendChild(allBtn);

        // По кнопці на кожну категорію
        Object.entries(byCategory)
            .sort((a, b) => b[1] - a[1])
            .forEach(([cat, count]) => {
                const btn = document.createElement('button');
                const isActive = this.searchCategoryFilter === cat;
                btn.className = 'search-filter-btn' + (isActive ? ' active' : '');
                btn.innerHTML = `${icons[cat] || '🗂️'} ${cat} <span class="search-filter-count">${count}</span>`;
                // Toggle: клік на активну — знімає фільтр; клік на іншу — встановлює
                btn.addEventListener('click', () => applyFilter(isActive ? null : cat));
                bar.appendChild(btn);
            });

        return bar;
    }

    escapeHtml(str) {
        return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    createFileCard(file) {
        const card = document.createElement('div');
        card.className = 'file-card';
        if (!this.bulkMode && this.selectedFileId === file.file_id) {
            card.classList.add('selected');
        }
        if (this.bulkMode && this.selectedFileIds.has(file.file_id)) {
            card.classList.add('bulk-selected');
        }

        const icon = this.getFileIcon(file.category);

        const checkboxHtml = this.bulkMode ? `
                <input type="checkbox" class="bulk-checkbox" 
                       ${this.selectedFileIds.has(file.file_id) ? 'checked' : ''}>` : '';

        card.innerHTML = `
            <div class="file-header">
                ${checkboxHtml}
                <div class="file-icon">${icon}</div>
                <span class="category-badge">${file.category}</span>
            </div>
            <div class="file-name" title="${file.filename}">${file.filename}</div>
            <div class="file-tags">
                ${file.tags.map(tag => `<span class="tag">#${tag}</span>`).join('')}
            </div>
            <div class="file-info">💾 ${this.formatSize(file.size)} | 🤖 AI: ${Math.round(file.confidence * 100)}%</div>
        `;

        if (this.bulkMode) {
            card.addEventListener('click', (e) => {
                if (e.target.type === 'checkbox') return;
                this.toggleBulkSelect(file.file_id);
            });
            const cb = card.querySelector('.bulk-checkbox');
            cb.addEventListener('change', () => this.toggleBulkSelect(file.file_id));
        } else {
            card.addEventListener('click', () => this.selectFile(file.file_id));
        }

        return card;
    }

    enableBulkMode() {
        this.bulkMode = true;
        this.selectedFileIds.clear();
        this.closeDetailsPanel();
        document.getElementById('bulkToolbar').style.display = 'flex';
        document.getElementById('bulkToggleBtn').classList.add('active');
        this.renderFiles();
        this.updateBulkToolbar();
    }

    disableBulkMode() {
        this.bulkMode = false;
        this.selectedFileIds.clear();
        document.getElementById('bulkToolbar').style.display = 'none';
        document.getElementById('bulkToggleBtn').classList.remove('active');
        document.getElementById('selectAllCheckbox').checked = false;
        this.renderFiles();
    }

    toggleBulkSelect(fileId) {
        if (this.selectedFileIds.has(fileId)) {
            this.selectedFileIds.delete(fileId);
        } else {
            this.selectedFileIds.add(fileId);
        }
        this.renderFiles();
        this.updateBulkToolbar();
    }

    updateBulkToolbar() {
        const count = this.selectedFileIds.size;
        const none = count === 0;
        document.getElementById('bulkSelectedCount').textContent = `${count} selected`;
        document.getElementById('bulkDeleteBtn').disabled = none;
        document.getElementById('bulkDownloadBtn').disabled = none;
        document.getElementById('bulkTagBtn').disabled = none;
        document.getElementById('bulkMoveBtn').disabled = none;
        document.getElementById('bulkRemoveTagBtn').disabled = none;
        const allSelected = this.files.length > 0 && count === this.files.length;
        document.getElementById('selectAllCheckbox').checked = allSelected;
        document.getElementById('selectAllCheckbox').indeterminate = count > 0 && !allSelected;
        // Оновлюємо і menu-кнопки File → вони відображають стан будь-якого вибору
        this.updateMenuFileButtons();
    }

    updateMenuFileButtons() {
        // Menu File → Download/Delete працюють з будь-яким активним вибором:
        // або bulk selectedFileIds (якщо bulk-режим), або одиночний selectedFileId
        const hasSelection = this.bulkMode
            ? this.selectedFileIds.size > 0
            : this.selectedFileId !== null;
        document.getElementById('menuDownloadSelected').disabled = !hasSelection;
        document.getElementById('menuDeleteSelected').disabled = !hasSelection;
    }

    async bulkDelete() {
        const count = this.selectedFileIds.size;
        if (count === 0) return;

        const confirmed = await this.showBulkDeleteConfirmDialog(count);
        if (!confirmed) return;

        this.showLoading();
        const ids = [...this.selectedFileIds];
        let successCount = 0;

        for (const fileId of ids) {
            try {
                const response = await fetch(`/api/files/${fileId}`, { method: 'DELETE' });
                if (response.ok) successCount++;
            } catch (e) {
                console.error('Error deleting file:', e);
            }
        }

        this.hideLoading();
        this.showSuccessMessage(`Видалено ${successCount} з ${count} файлів`);
        this.disableBulkMode();
        await this.loadFiles();
        await this.updateStats();
    }

    async showBulkDeleteConfirmDialog(count) {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'duplicate-dialog-overlay';

            const dialog = document.createElement('div');
            dialog.className = 'duplicate-dialog';
            dialog.innerHTML = `
                <div class="duplicate-dialog-header">
                    <h3>🗑️ Масове видалення</h3>
                </div>
                <div class="duplicate-dialog-content">
                    <p class="duplicate-warning">Ви впевнені, що хочете видалити <strong>${count} файл${count === 1 ? '' : count < 5 ? 'и' : 'ів'}</strong>?</p>
                    <p class="delete-warning-text">⚠️ Цю дію неможливо скасувати!</p>
                </div>
                <div class="duplicate-dialog-actions">
                    <button class="dialog-btn btn-cancel" data-action="cancel">❌ Скасувати</button>
                    <button class="dialog-btn btn-delete" data-action="delete">🗑️ Видалити всі</button>
                </div>
            `;

            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            dialog.querySelector('[data-action="delete"]').addEventListener('click', () => {
                document.body.removeChild(overlay);
                resolve(true);
            });
            dialog.querySelector('[data-action="cancel"]').addEventListener('click', () => {
                document.body.removeChild(overlay);
                resolve(false);
            });
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) { document.body.removeChild(overlay); resolve(false); }
            });
        });
    }

    async bulkDownload() {
        const ids = [...this.selectedFileIds];
        if (ids.length === 0) return;

        if (ids.length === 1) {
            // Завантажуємо один файл напряму
            const file = this.files.find(f => f.file_id === ids[0]);
            if (file) {
                const a = document.createElement('a');
                a.href = `/api/files/${ids[0]}/download`;
                a.download = file.filename;
                a.click();
            }
        } else {
            // Завантажуємо кілька файлів по черзі з невеликою затримкою
            this.showToast(`Завантаження ${ids.length} файлів...`, 'info');
            for (const fileId of ids) {
                const file = this.files.find(f => f.file_id === fileId);
                if (file) {
                    const a = document.createElement('a');
                    a.href = `/api/files/${fileId}/download`;
                    a.download = file.filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    await new Promise(r => setTimeout(r, 300)); // затримка між файлами
                }
            }
            this.showSuccessMessage(`Завантаження ${ids.length} файлів розпочато`);
        }
    }

    async bulkAddTag() {
        const ids = [...this.selectedFileIds];
        if (ids.length === 0) return;

        const tag = await this.showBulkTagDialog(ids.length);
        if (!tag) return;

        this.showLoading();
        let successCount = 0;

        for (const fileId of ids) {
            try {
                const response = await fetch(`/api/files/${fileId}/tags`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tag })
                });
                if (response.ok) successCount++;
            } catch (e) {
                console.error('Error adding tag:', e);
            }
        }

        this.hideLoading();
        this.showSuccessMessage(`Тег #${tag} додано до ${successCount} файлів`);
        await this.loadFiles();
    }

    async showBulkTagDialog(count) {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'duplicate-dialog-overlay';

            const dialog = document.createElement('div');
            dialog.className = 'duplicate-dialog';
            dialog.innerHTML = `
                <div class="duplicate-dialog-header">
                    <h3>🏷️ Додати тег до ${count} файл${count === 1 ? 'у' : count < 5 ? 'ів' : 'ів'}</h3>
                </div>
                <div class="duplicate-dialog-content">
                    <p class="duplicate-warning">Введіть тег, який буде додано до всіх вибраних файлів:</p>
                    <div class="rename-input-container">
                        <div class="rename-input-group">
                            <span class="rename-extension">#</span>
                            <input type="text" class="rename-input" id="bulkTagInput" 
                                   placeholder="назва тегу..." autocomplete="off">
                        </div>
                        <p class="rename-hint">💡 Тег буде нормалізовано (нижній регістр)</p>
                    </div>
                </div>
                <div class="duplicate-dialog-actions">
                    <button class="dialog-btn btn-cancel" data-action="cancel">❌ Скасувати</button>
                    <button class="dialog-btn btn-primary" data-action="save">✅ Додати тег</button>
                </div>
            `;

            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            const input = dialog.querySelector('#bulkTagInput');
            input.focus();

            const handleSave = () => {
                const val = input.value.trim().toLowerCase();
                if (!val) {
                    input.classList.add('error-shake');
                    setTimeout(() => input.classList.remove('error-shake'), 500);
                    return;
                }
                document.body.removeChild(overlay);
                resolve(val);
            };

            const handleCancel = () => {
                document.body.removeChild(overlay);
                resolve(null);
            };

            dialog.querySelector('[data-action="save"]').addEventListener('click', handleSave);
            dialog.querySelector('[data-action="cancel"]').addEventListener('click', handleCancel);
            input.addEventListener('keypress', e => { if (e.key === 'Enter') handleSave(); });
            input.addEventListener('keydown', e => { if (e.key === 'Escape') handleCancel(); });
            overlay.addEventListener('click', e => { if (e.target === overlay) handleCancel(); });
        });
    }

    async bulkMoveCategory() {
        const ids = [...this.selectedFileIds];
        if (ids.length === 0) return;

        // Динамічно збираємо категорії з поточних файлів + базові
        const baseCats = ['document', 'code', 'image', 'video', 'audio', 'archive', 'other'];
        const existingCats = [...new Set(this.files.map(f => f.category))];
        const categories = [...new Set([...baseCats, ...existingCats])];

        const newCategory = await this.showBulkMoveCategoryDialog(ids.length, categories);
        if (!newCategory) return;

        this.showLoading();
        let successCount = 0;

        for (const fileId of ids) {
            try {
                const response = await fetch(`/api/files/${fileId}/category`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ category: newCategory })
                });
                if (response.ok) successCount++;
            } catch (e) {
                console.error('Error moving file:', e);
            }
        }

        this.hideLoading();
        // Спочатку оновлюємо дані, потім виходимо з bulk-режиму — щоб renderFiles мав актуальні дані
        await this.loadCategoryTabs();   // нова категорія одразу з'являється в tabs
        await this.loadFiles();
        await this.updateStats();
        this.disableBulkMode();
        const s = successCount;
        this.showSuccessMessage(`${s} файл${s===1?'':s<5?'и':'ів'} переміщено до "${newCategory}"`);
    }

    async showBulkMoveCategoryDialog(count, categories) {
        // Завантажуємо актуальний список категорій з API (включно з кастомними)
        let apiCategories = categories.map(id => ({ id, label: id.toUpperCase() }));
        try {
            const res = await fetch('/api/categories');
            if (res.ok) apiCategories = await res.json();
        } catch (e) { /* fallback до переданих */ }

        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'duplicate-dialog-overlay';

            const categoryBtns = apiCategories.map(cat => `
                <button class="category-choice-btn" data-category="${cat.id}">
                    ${cat.label}
                </button>
            `).join('');

            const dialog = document.createElement('div');
            dialog.className = 'duplicate-dialog';
            dialog.innerHTML = `
                <div class="duplicate-dialog-header">
                    <h3>📂 Перемістити ${count} файл${count === 1 ? '' : count < 5 ? 'и' : 'ів'}</h3>
                </div>
                <div class="duplicate-dialog-content">
                    <p class="duplicate-warning">Оберіть категорію призначення:</p>
                    <div class="category-choice-grid">
                        ${categoryBtns}
                    </div>
                </div>
                <div class="duplicate-dialog-actions">
                    <button class="dialog-btn btn-cancel" data-action="cancel">❌ Скасувати</button>
                </div>
            `;

            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            dialog.querySelectorAll('.category-choice-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    document.body.removeChild(overlay);
                    resolve(btn.dataset.category);
                });
            });

            dialog.querySelector('[data-action="cancel"]').addEventListener('click', () => {
                document.body.removeChild(overlay);
                resolve(null);
            });
            overlay.addEventListener('click', e => {
                if (e.target === overlay) { document.body.removeChild(overlay); resolve(null); }
            });
        });
    }

    getFileIcon(category) {
        const icons = {
            'document': '📄',
            'code': '💻',
            'image': '🖼️',
            'video': '🎥',
            'audio': '🎵',
            'archive': '📦',
            'other': '📌'
        };
        return icons[category] || '📌';
    }

    async selectFile(fileId) {
        this.selectedFileId = fileId;
        this.renderFiles();
        await this.showFileDetails(fileId);
        this.openDetailsPanel();
        // Активуємо menu File → Download/Delete коли файл вибрано кліком
        this.updateMenuFileButtons();
    }

    openDetailsPanel() {
        const detailsPanel = document.getElementById('detailsPanel');
        const mainContainer = document.querySelector('.main-container');
        const detailsOverlay = document.getElementById('detailsOverlay');

        detailsPanel.classList.remove('hidden');
        mainContainer.classList.remove('details-closed');

        // Показуємо overlay на мобільних
        if (window.innerWidth <= 992) {
            detailsOverlay.style.display = 'block';
        }
    }

    closeDetailsPanel() {
        const detailsPanel = document.getElementById('detailsPanel');
        const mainContainer = document.querySelector('.main-container');
        const detailsOverlay = document.getElementById('detailsOverlay');

        detailsPanel.classList.add('hidden');
        mainContainer.classList.add('details-closed');
        detailsOverlay.style.display = 'none';

        // Знімаємо одиночний вибір і деактивуємо menu-кнопки
        this.selectedFileId = null;
        this.renderFiles();
        this.updateMenuFileButtons();
    }

    async showFileDetails(fileId) {
        const detailsContent = document.getElementById('detailsContent');

        try {
            const response = await fetch(`/api/files/${fileId}`);
            const file = await response.json();

            detailsContent.innerHTML = `
                <div class="detail-section">
                    <span class="detail-label">FILENAME</span>
                    <span class="detail-value">${this._esc(file.filename)}</span>
                </div>
                <div class="detail-section">
                    <span class="detail-label">CATEGORY</span>
                    <span class="detail-value">${file.category.toUpperCase()}</span>
                </div>
                <div class="detail-section">
                    <span class="detail-label">SIZE</span>
                    <span class="detail-value">${this.formatSize(file.size)}</span>
                </div>
                <div class="detail-section">
                    <span class="detail-label">SUBCATEGORY</span>
                    <span class="detail-value">${file.subcategory.toUpperCase()}</span>
                </div>
                <div class="detail-section confidence-container">
                    <span class="detail-label">AI CONFIDENCE</span>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${file.confidence * 100}%"></div>
                    </div>
                    <span class="confidence-text">${Math.round(file.confidence * 100)}%</span>
                </div>
                <div class="detail-section">
                    <span class="detail-label">🏷️ NEURAL TAGS</span>
                    <div class="tags-display">
                        ${file.tags.map(tag => `
                            <div class="tag-item">
                                <span class="tag-text">#${tag}</span>
                                <button class="tag-remove" onclick="app.removeTag('${fileId}', '${tag}')">✖</button>
                            </div>
                        `).join('')}
                    </div>
                </div>
                <div class="detail-section">
                    <span class="detail-label">➕ ADD CUSTOM TAG</span>
                    <div class="tag-input-container">
                        <input type="text" class="tag-input" id="tagInput"
                               placeholder="Enter tag..."
                               onkeypress="if(event.key==='Enter') app.addTag('${fileId}')">
                        <button class="add-tag-btn" onclick="app.addTag('${fileId}')">➕</button>
                    </div>
                </div>
                <div class="detail-section">
                    <span class="detail-label">UPLOAD DATE</span>
                    <span class="detail-value">${this.formatDate(file.upload_date)}</span>
                </div>

                <div class="pv-section">
                    <div class="pv-header">
                        <span class="pv-title">👁 PREVIEW</span>
                        <div class="pv-header-right">
                            <span class="pv-badge" id="pvBadge"></span>
                            <button class="pv-collapse-btn" id="pvCollapseBtn" title="Згорнути / Розгорнути">▼</button>
                        </div>
                    </div>
                    <div class="pv-body" id="pvBody">
                        <div class="pv-loading"><div class="pv-spinner"></div><span>Завантаження…</span></div>
                    </div>
                </div>

                <button class="delete-btn" onclick="app.deleteFile('${fileId}')">
                    🗑️ DELETE FILE
                </button>
            `;

            // Запускаємо прев'ю паралельно
            this._pvLoad(fileId);

        } catch (error) {
            console.error('Error loading file details:', error);
        }
    }

    // ══════════════════════════════════════════════════════════════
    //  FILE PREVIEW ENGINE
    // ══════════════════════════════════════════════════════════════

    _esc(str) {
        return String(str)
            .replace(/&/g,'&amp;').replace(/</g,'&lt;')
            .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    }

    async _pvLoad(fileId) {
        const body    = document.getElementById('pvBody');
        const badge   = document.getElementById('pvBadge');
        const colBtn  = document.getElementById('pvCollapseBtn');
        if (!body) return;

        // Collapse / expand toggle
        let collapsed = false;
        colBtn && colBtn.addEventListener('click', () => {
            collapsed = !collapsed;
            body.style.display = collapsed ? 'none' : '';
            colBtn.textContent = collapsed ? '▶' : '▼';
        });

        try {
            const meta = await fetch(`/api/files/${fileId}/preview-meta`).then(r => r.json());
            const kind = meta.kind || 'none';
            const url  = `/api/files/${fileId}/preview`;

            const KIND_LABELS = {
                image:'🖼 Зображення', video:'🎥 Відео', audio:'🎵 Аудіо',
                pdf:'📄 PDF', sheet:'📊 Таблиця', word:'📝 Документ',
                archive:'📦 Архів', text:'💻 Код / Текст',
            };
            if (badge) badge.textContent = KIND_LABELS[kind] || '';

            if (kind === 'none') {
                body.innerHTML = `<div class="pv-unsupported"><span>🚫</span><p>Прев'ю недоступне для цього формату</p></div>`;
                return;
            }

            switch (kind) {
                case 'image':   this._pvImage(body, url); break;
                case 'video':   this._pvVideo(body, url, meta); break;
                case 'audio':   this._pvAudio(body, url, meta); break;
                case 'pdf':     this._pvPDF(body, url); break;
                case 'sheet':   await this._pvSheet(body, url); break;
                case 'word':    await this._pvWord(body, url); break;
                case 'archive': await this._pvArchive(body, url); break;
                case 'text':    await this._pvText(body, url, meta.lang || 'text'); break;
            }
        } catch(e) {
            if (body) body.innerHTML = `<div class="pv-error">⚠️ Помилка завантаження прев'ю</div>`;
            console.error('Preview error:', e);
        }
    }

    _pvImage(body, url) {
        body.innerHTML = `
            <div class="pv-img-wrap">
                <img class="pv-img" src="${url}" alt="preview" loading="lazy"
                     onerror="this.closest('.pv-img-wrap').innerHTML='<span class=pv-error>❌ Не вдалось завантажити зображення</span>'">
            </div>`;
    }

    _pvVideo(body, url, meta) {
        body.innerHTML = `
            <video class="pv-video" controls preload="metadata">
                <source src="${url}" type="${meta.mime || 'video/mp4'}">
                <p>Ваш браузер не підтримує відтворення відео.</p>
            </video>`;
    }

    _pvAudio(body, url, meta) {
        body.innerHTML = `
            <div class="pv-audio-wrap">
                <div class="pv-audio-icon">🎵</div>
                <audio class="pv-audio" controls preload="metadata">
                    <source src="${url}" type="${meta.mime || 'audio/mpeg'}">
                </audio>
            </div>`;
    }

    _pvPDF(body, url) {
        body.innerHTML = `
            <div class="pv-pdf-wrap">
                <iframe class="pv-pdf" src="${url}#toolbar=0&navpanes=0" loading="lazy" title="PDF preview"></iframe>
                <a class="pv-pdf-link" href="${url}" target="_blank">🔗 Відкрити в новій вкладці</a>
            </div>`;
    }

    async _pvSheet(body, url) {
        const data = await fetch(url).then(r => r.json());
        if (data.error) { body.innerHTML = `<div class="pv-error">⚠️ ${this._esc(data.error)}</div>`; return; }

        const { headers, rows, total_rows, total_cols, truncated, truncated_cols } = data;
        const note = `${total_rows.toLocaleString()} рядків`
            + (total_cols > headers.length ? ` · ${total_cols} колонок` : '')
            + (truncated || truncated_cols ? ' · часткове прев\'ю' : '');

        let html = `<div class="pv-sheet-meta">${note}</div>
                    <div class="pv-table-wrap"><table class="pv-table">
                    <thead><tr>${headers.map(h => `<th>${this._esc(String(h))}</th>`).join('')}</tr></thead>
                    <tbody>`;
        rows.forEach(row => {
            html += `<tr>${row.map(c => `<td>${this._esc(String(c ?? ''))}</td>`).join('')}</tr>`;
        });
        html += `</tbody></table></div>`;
        if (truncated) html += `<div class="pv-truncated">⤵ Показано ${rows.length} з ${total_rows.toLocaleString()} рядків</div>`;
        body.innerHTML = html;
    }

    async _pvWord(body, url) {
        const data = await fetch(url).then(r => r.json());
        if (data.error) { body.innerHTML = `<div class="pv-error">⚠️ ${this._esc(data.error)}</div>`; return; }

        const { paragraphs, total, truncated } = data;
        let html = `<div class="pv-word">`;
        paragraphs.forEach(p => {
            const t = p.trim();
            if (!t) return;
            // Евристика: короткий рядок з великих літер → заголовок
            const isHead = t.length < 80 && t === t.toUpperCase() && /[A-ZА-ЯЁІЇЄ]/.test(t);
            html += isHead
                ? `<p class="pv-word-h">${this._esc(t)}</p>`
                : `<p class="pv-word-p">${this._esc(t)}</p>`;
        });
        html += `</div>`;
        if (truncated) html += `<div class="pv-truncated">⤵ Показано ${paragraphs.length} з ${total} абзаців</div>`;
        body.innerHTML = html;
    }

    async _pvArchive(body, url) {
        const data = await fetch(url).then(r => r.json());
        if (data.error) { body.innerHTML = `<div class="pv-error">⚠️ ${this._esc(data.error)}</div>`; return; }

        const { entries, total, truncated } = data;
        const EXT_ICON = {
            py:'🐍', js:'📜', ts:'📜', json:'📋', yaml:'📋', yml:'📋', toml:'📋',
            txt:'📄', md:'📄', pdf:'📕', docx:'📘', xlsx:'📗', csv:'📊',
            png:'🖼', jpg:'🖼', jpeg:'🖼', gif:'🖼', svg:'🖼', webp:'🖼',
            mp4:'🎥', mov:'🎥', avi:'🎥', webm:'🎥',
            mp3:'🎵', wav:'🎵', ogg:'🎵', flac:'🎵',
            zip:'🗜', tar:'🗜', gz:'🗜', rar:'🗜',
            html:'🌐', css:'🎨', xml:'📋', sh:'🖥', bat:'🖥',
            exe:'⚙', dll:'⚙', c:'🔧', cpp:'🔧', h:'🔧',
        };

        let html = `<div class="pv-arch-meta">${total.toLocaleString()} об'єктів в архіві</div>
                    <div class="pv-arch-list">`;
        entries.forEach(e => {
            const ext  = e.name.split('.').pop().toLowerCase();
            const icon = e.is_dir ? '📁' : (EXT_ICON[ext] || '📄');
            const sz   = e.is_dir ? '' : `<span class="pv-arch-sz">${this.formatSize(e.size)}</span>`;
            html += `<div class="pv-arch-row">
                        <span class="pv-arch-icon">${icon}</span>
                        <span class="pv-arch-name" title="${this._esc(e.name)}">${this._esc(e.name)}</span>
                        ${sz}
                     </div>`;
        });
        html += `</div>`;
        if (truncated) html += `<div class="pv-truncated">⤵ Показано ${entries.length} з ${total.toLocaleString()} файлів</div>`;
        body.innerHTML = html;
    }

    async _pvText(body, url, lang) {
        const data = await fetch(url).then(r => r.json());
        if (data.error) { body.innerHTML = `<div class="pv-error">⚠️ ${this._esc(data.error)}</div>`; return; }

        const { content, lines, truncated } = data;
        const hi = this._pvHighlight(this._esc(content), lang);
        body.innerHTML = `
            <div class="pv-code-meta">${lines.toLocaleString()} рядків · <span class="pv-code-lang">${lang}</span></div>
            <div class="pv-code-wrap"><pre class="pv-code">${hi}</pre></div>
            ${truncated ? `<div class="pv-truncated">⤵ Файл обрізано для прев'ю</div>` : ''}`;
    }

    _pvHighlight(escaped, lang) {
        const KW = {
            python:     'def|class|import|from|return|if|elif|else|for|while|try|except|finally|with|as|pass|break|continue|raise|lambda|yield|and|or|not|in|is|None|True|False|async|await|global|nonlocal',
            javascript: 'function|class|const|let|var|return|if|else|for|while|try|catch|finally|import|export|default|new|this|typeof|instanceof|async|await|null|undefined|true|false|break|continue|switch|case|of|delete|void',
            typescript: 'function|class|const|let|var|return|if|else|for|while|try|catch|finally|import|export|interface|type|enum|async|await|null|undefined|true|false|readonly|private|public|protected|abstract|implements|extends',
            sql:        'SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|GROUP|BY|ORDER|HAVING|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TABLE|INDEX|VIEW|AS|AND|OR|NOT|NULL|IN|LIKE|BETWEEN|DISTINCT|UNION|ALL|EXISTS',
            bash:       'if|then|else|elif|fi|for|while|do|done|case|esac|function|return|local|export|echo|exit|true|false|in|source',
            java:       'public|private|protected|class|interface|extends|implements|return|if|else|for|while|try|catch|finally|new|this|static|final|void|import|package|null|true|false|break|continue|switch|case',
            go:         'func|package|import|return|if|else|for|range|switch|case|default|var|const|type|struct|interface|go|chan|select|defer|break|continue|nil|true|false',
            rust:       'fn|let|mut|const|struct|enum|impl|trait|use|pub|mod|return|if|else|match|for|while|loop|break|continue|true|false|None|Some|Ok|Err|async|await',
        };

        const kwList = KW[lang];
        let out = escaped
            // Рядки одинарні та подвійні
            .replace(/(&#39;[^&#\n]*?&#39;|&quot;[^&\n]*?&quot;|`[^`\n]*?`)/g,
                     '<span class="pv-s">$1</span>')
            // Числа
            .replace(/(?<![.\w])(\d+\.?\d*)(?![\w])/g,
                     '<span class="pv-n">$1</span>')
            // Коментарі //  та  #
            .replace(/(\/\/[^\n]*|#(?![\da-fA-F]{3,8})[^\n]*)/g,
                     '<span class="pv-c">$&</span>');

        if (kwList) {
            out = out.replace(
                new RegExp(`(?<![\\w.#])\\b(${kwList})\\b(?![^<]*>)`, 'g'),
                '<span class="pv-k">$1</span>'
            );
        }
        return out;
    }

    async addTag(fileId) {
        const tagInput = document.getElementById('tagInput');
        const tag = tagInput.value.trim();

        if (!tag) return;

        try {
            const response = await fetch(`/api/files/${fileId}/tags`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ tag })
            });

            if (response.ok) {
                tagInput.value = '';
                await this.loadFiles();
                await this.showFileDetails(fileId);
                this.updateStats();
            }
        } catch (error) {
            console.error('Error adding tag:', error);
            alert('Error adding tag');
        }
    }

    async removeTag(fileId, tag) {
        try {
            const response = await fetch(`/api/files/${fileId}/tags/${encodeURIComponent(tag)}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                await this.loadFiles();
                await this.showFileDetails(fileId);
                this.updateStats();
            }
        } catch (error) {
            console.error('Error removing tag:', error);
            alert('Error removing tag');
        }
    }

    async deleteFile(fileId) {
        // Отримуємо інформацію про файл
        const file = this.files.find(f => f.file_id === fileId);
        if (!file) return;

        // Показуємо графічний діалог підтвердження
        const confirmed = await this.showDeleteConfirmDialog(file.filename);

        if (!confirmed) {
            return;
        }

        try {
            const response = await fetch(`/api/files/${fileId}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                // Показуємо повідомлення про успіх
                this.showSuccessMessage('Файл успішно видалено');

                this.selectedFileId = null;
                await this.loadFiles();
                document.getElementById('detailsContent').innerHTML = `
                    <div class="no-selection">
                        <p class="warning-text">⚠️ SELECT FILE TO VIEW DETAILS</p>
                    </div>
                `;
                this.updateStats();
                this.closeDetailsPanel();
            } else {
                throw new Error('Delete failed');
            }
        } catch (error) {
            console.error('Error deleting file:', error);
            this.showErrorMessage('Помилка при видаленні файлу');
        }
    }

    async showDeleteConfirmDialog(fileName) {
        // Показує діалог підтвердження видалення
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'duplicate-dialog-overlay';

            const dialog = document.createElement('div');
            dialog.className = 'duplicate-dialog';

            dialog.innerHTML = `
                <div class="duplicate-dialog-header">
                    <h3>🗑️ Підтвердження видалення</h3>
                </div>
                <div class="duplicate-dialog-content">
                    <p class="duplicate-warning">
                        Ви впевнені, що хочете видалити файл?
                    </p>
                    <div class="delete-file-info">
                        <div class="file-name-display">
                            📄 <strong>${fileName}</strong>
                        </div>
                    </div>
                    <p class="delete-warning-text">
                        ⚠️ Цю дію неможливо скасувати!
                    </p>
                </div>
                <div class="duplicate-dialog-actions">
                    <button class="dialog-btn btn-cancel" data-action="cancel">
                        ❌ Скасувати
                    </button>
                    <button class="dialog-btn btn-delete" data-action="delete">
                        🗑️ Видалити
                    </button>
                </div>
            `;

            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            const deleteBtn = dialog.querySelector('[data-action="delete"]');
            const cancelBtn = dialog.querySelector('[data-action="cancel"]');

            const handleDelete = () => {
                document.body.removeChild(overlay);
                resolve(true);
            };

            const handleCancel = () => {
                document.body.removeChild(overlay);
                resolve(false);
            };

            deleteBtn.addEventListener('click', handleDelete);
            cancelBtn.addEventListener('click', handleCancel);

            // Escape = скасувати
            document.addEventListener('keydown', function escHandler(e) {
                if (e.key === 'Escape') {
                    handleCancel();
                    document.removeEventListener('keydown', escHandler);
                }
            });

            // Закриття по кліку на overlay
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    handleCancel();
                }
            });
        });
    }

    showSuccessMessage(message) {
        // Показує повідомлення про успіх
        this.showToast(message, 'success');
    }

    showErrorMessage(message) {
        // Показує повідомлення про помилку
        this.showToast(message, 'error');
    }

    showToast(message, type = 'info') {
        // Показує toast повідомлення
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;

        const icon = type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️';
        toast.innerHTML = `${icon} ${message}`;

        document.body.appendChild(toast);

        // Анімація появи
        setTimeout(() => toast.classList.add('show'), 10);

        // Автоматичне зникнення через 3 секунди
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => {
                if (toast.parentNode) {
                    document.body.removeChild(toast);
                }
            }, 300);
        }, 3000);
    }

    async updateStats() {
        try {
            const response = await fetch('/api/stats');
            const stats = await response.json();

            document.getElementById('totalFiles').textContent = stats.total_files;
            document.getElementById('totalSize').textContent = this.formatSize(stats.total_size);
        } catch (error) {
            console.error('Error updating stats:', error);
        }
    }

    formatSize(bytes) {
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let size = bytes;
        let unitIndex = 0;

        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex++;
        }

        return `${size.toFixed(1)} ${units[unitIndex]}`;
    }

    formatDate(dateString) {
        const date = new Date(dateString);
        return date.toLocaleString('uk-UA', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }

    showLoading() {
        document.getElementById('loadingOverlay').style.display = 'flex';
    }

    hideLoading() {
        document.getElementById('loadingOverlay').style.display = 'none';
    }

    // ══════════════════════════════════════════════════════
    //  BULK REMOVE TAG
    // ══════════════════════════════════════════════════════

    // ── Menu File: Download/Delete ──────────────────────────
    // Працюють з будь-яким активним вибором:
    // bulk-режим → selectedFileIds, одиночний → selectedFileId

    async menuDownload() {
        if (this.bulkMode && this.selectedFileIds.size > 0) {
            return this.bulkDownload();
        }
        if (this.selectedFileId) {
            const file = this.files.find(f => f.file_id === this.selectedFileId);
            if (file) {
                const a = document.createElement('a');
                a.href = `/api/files/${this.selectedFileId}/download`;
                a.download = file.filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
            }
            return;
        }
        this.showToast('Виберіть файл для завантаження', 'info');
    }

    async menuDelete() {
        if (this.bulkMode && this.selectedFileIds.size > 0) {
            return this.bulkDelete();
        }
        if (this.selectedFileId) {
            return this.deleteFile(this.selectedFileId);
        }
        this.showToast('Виберіть файл для видалення', 'info');
    }

    async bulkRemoveTag() {
        const ids = [...this.selectedFileIds];
        if (ids.length === 0) return;

        const selectedFiles = this.files.filter(f => this.selectedFileIds.has(f.file_id));
        const allTags = [...new Set(selectedFiles.flatMap(f => f.tags))].sort();

        const tag = await this.showBulkRemoveTagDialog(ids.length, allTags);
        if (!tag) return;

        this.showLoading();
        try {
            const response = await fetch('/api/bulk/remove-tag', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_ids: ids, tag })
            });
            const data = await response.json();
            this.hideLoading();
            this.showSuccessMessage(`Тег #${tag} видалено з ${data.updated} файлів`);
        } catch (e) {
            this.hideLoading();
            this.showToast('Помилка видалення тегу', 'error');
        }
        await this.loadFiles();
    }

    async showBulkRemoveTagDialog(count, existingTags) {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'duplicate-dialog-overlay';

            const tagChips = existingTags.length > 0
                ? `<div class="tag-chips-hint">
                    <p class="rename-hint">Теги у вибраних файлах (клікніть для вибору):</p>
                    <div class="tag-chips">
                        ${existingTags.map(t => `<button class="tag-chip" data-tag="${t}">#${t}</button>`).join('')}
                    </div>
                   </div>`
                : '';

            const dialog = document.createElement('div');
            dialog.className = 'duplicate-dialog';
            dialog.innerHTML = `
                <div class="duplicate-dialog-header">
                    <h3>🏷️ Видалити тег з ${count} файл${count === 1 ? 'у' : 'ів'}</h3>
                </div>
                <div class="duplicate-dialog-content">
                    <p class="duplicate-warning">Введіть або оберіть тег для видалення:</p>
                    <div class="rename-input-container">
                        <div class="rename-input-group">
                            <span class="rename-extension">#</span>
                            <input type="text" class="rename-input" id="removeTagInput"
                                   placeholder="назва тегу..." autocomplete="off">
                        </div>
                    </div>
                    ${tagChips}
                </div>
                <div class="duplicate-dialog-actions">
                    <button class="dialog-btn btn-cancel" data-action="cancel">❌ Скасувати</button>
                    <button class="dialog-btn btn-delete" data-action="save">🗑️ Видалити тег</button>
                </div>
            `;
            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            const input = dialog.querySelector('#removeTagInput');
            input.focus();

            dialog.querySelectorAll('.tag-chip').forEach(chip => {
                chip.addEventListener('click', () => {
                    input.value = chip.dataset.tag;
                    dialog.querySelectorAll('.tag-chip').forEach(c => c.classList.remove('selected'));
                    chip.classList.add('selected');
                });
            });

            const handleSave = () => {
                const val = input.value.trim().toLowerCase();
                if (!val) { input.classList.add('error-shake'); setTimeout(() => input.classList.remove('error-shake'), 500); return; }
                document.body.removeChild(overlay);
                resolve(val);
            };
            const handleCancel = () => { document.body.removeChild(overlay); resolve(null); };

            dialog.querySelector('[data-action="save"]').addEventListener('click', handleSave);
            dialog.querySelector('[data-action="cancel"]').addEventListener('click', handleCancel);
            input.addEventListener('keypress', e => { if (e.key === 'Enter') handleSave(); });
            input.addEventListener('keydown', e => { if (e.key === 'Escape') handleCancel(); });
            overlay.addEventListener('click', e => { if (e.target === overlay) handleCancel(); });
        });
    }

    // ══════════════════════════════════════════════════════
    //  MANAGE CATEGORIES & SUBCATEGORIES
    // ══════════════════════════════════════════════════════

    async manageCategoriesDialog() {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'duplicate-dialog-overlay';
            const dialog = document.createElement('div');
            dialog.className = 'duplicate-dialog manage-dialog';
            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            const close = () => { document.body.removeChild(overlay); this.loadCategoryTabs(); this.loadFiles(); this.updateStats(); resolve(); };

            const render = async () => {
                const cats = await this._fetchCategories();
                const base = new Set(['document','code','image','video','audio','archive','other']);
                dialog.innerHTML = `
                    <div class="duplicate-dialog-header">
                        <h3>🗂️ Управління категоріями</h3>
                    </div>
                    <div class="duplicate-dialog-content">
                        <div class="manage-section">
                            <div class="manage-section-header">
                                <span class="manage-section-title">📂 Категорії</span>
                                <button class="manage-add-btn" id="createCategoryBtn">＋ Нова категорія</button>
                            </div>
                            <div class="manage-list">
                                ${cats.map(cat => `
                                    <div class="manage-item">
                                        <span class="manage-item-label">${cat.label}</span>
                                        <div class="manage-item-actions">
                                            <button class="manage-sub-btn" data-cat="${cat.id}">🗂️ Підкатегорії</button>
                                            ${!base.has(cat.id) ? `<button class="manage-del-btn" data-cat="${cat.id}">🗑️</button>` : ''}
                                        </div>
                                    </div>`).join('')}
                            </div>
                        </div>
                    </div>
                    <div class="duplicate-dialog-actions">
                        <button class="dialog-btn btn-cancel" id="manageDoneBtn">✕ Закрити</button>
                    </div>
                `;

                dialog.querySelector('#manageDoneBtn').addEventListener('click', close);

                dialog.querySelector('#createCategoryBtn').addEventListener('click', async () => {
                    const name = await this.showInputDialog('➕ Нова категорія', 'Назва (латиниця/цифри/дефіс):', 'my-category');
                    if (!name) return;
                    const res = await fetch('/api/categories', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({name}) });
                    const d = await res.json();
                    if (!res.ok) { this.showToast(d.error || 'Помилка', 'error'); return; }
                    this.showToast(`Категорію "${name}" створено`, 'success');
                    await this.loadCategoryTabs();   // оновлюємо tabs в toolbar
                    await render();
                });

                dialog.querySelectorAll('.manage-del-btn[data-cat]').forEach(btn => {
                    btn.addEventListener('click', async () => {
                        const id = btn.dataset.cat;
                        const ok = await this.showConfirmDialog(`Видалити "${id}"?`, 'Файли перемістяться до "Other"');
                        if (!ok) return;
                        const res = await fetch(`/api/categories/${id}`, { method: 'DELETE' });
                        const d = await res.json();
                        if (!res.ok) { this.showToast(d.error || 'Помилка', 'error'); return; }
                        this.showToast(`"${id}" видалено, ${d.files_moved} файлів переміщено`, 'success');
                        await this.loadCategoryTabs();   // оновлюємо tabs в toolbar
                        // якщо зараз переглядаємо видалену категорію — скидаємо на all
                        if (this.currentCategory === id) this.setCategory('all');
                        await render();
                    });
                });

                dialog.querySelectorAll('.manage-sub-btn[data-cat]').forEach(btn => {
                    btn.addEventListener('click', async () => {
                        document.body.removeChild(overlay); resolve();
                        await this.manageSubcategoriesDialog(btn.dataset.cat);
                    });
                });
            };

            render();
            overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
        });
    }

    async manageSubcategoriesDialog(categoryId) {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'duplicate-dialog-overlay';
            const dialog = document.createElement('div');
            dialog.className = 'duplicate-dialog manage-dialog';
            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            const close = () => { document.body.removeChild(overlay); this.loadFiles(); resolve(); };

            // Системні підкатегорії отримуємо з API разом з повним списком.
            // Сервер повертає їх в стабільному порядку: спочатку системні, потім кастомні.
            // Ми вважаємо системними ті, що НЕ були додані через POST /subcategories,
            // тобто ті що прийшли з config.yaml (перевіряє бекенд через SUBCATEGORY_RULES).
            // Для UI достатньо: якщо підкатегорія є в systemSubsFromApi — показуємо badge, без кнопки Delete.
            // systemSubsFromApi заповнюється нижче після отримання списку.
            const systemSubs = new Set();

            const render = async () => {
                let subs = [];
                try { const r = await fetch(`/api/categories/${categoryId}/subcategories`); subs = await r.json(); } catch(e) {}
                // Системні підкатегорії: запитуємо окремо (повертає тільки системні з config.yaml)
                try {
                    const r2 = await fetch(`/api/subcategories/${categoryId}`);
                    const systemList = await r2.json();
                    systemList.forEach(s => systemSubs.add(s));
                } catch(e) {}
                systemSubs.add('general'); // general завжди системна

                dialog.innerHTML = `
                    <div class="duplicate-dialog-header">
                        <h3>🗂️ Підкатегорії: <span style="color:var(--accent)">${categoryId.toUpperCase()}</span></h3>
                    </div>
                    <div class="duplicate-dialog-content">
                        <div class="manage-section">
                            <div class="manage-section-header">
                                <span class="manage-section-title">Підкатегорії</span>
                                <button class="manage-add-btn" id="createSubBtn">＋ Нова</button>
                            </div>
                            <div class="manage-list">
                                ${subs.map(sub => `
                                    <div class="manage-item">
                                        <span class="manage-item-label">
                                            ${sub === 'general' ? '📁' : '🗂️'} ${sub}
                                            ${systemSubs.has(sub) ? '<span class="manage-system-badge">system</span>' : ''}
                                        </span>
                                        ${!systemSubs.has(sub) ? `
                                        <div class="manage-item-actions">
                                            <button class="manage-del-btn" data-sub="${sub}">🗑️</button>
                                        </div>` : ''}
                                    </div>`).join('')}
                            </div>
                        </div>
                    </div>
                    <div class="duplicate-dialog-actions">
                        <button class="dialog-btn btn-rename" id="subBackBtn">← Назад</button>
                        <button class="dialog-btn btn-cancel" id="subCloseBtn">✕ Закрити</button>
                    </div>
                `;

                dialog.querySelector('#subBackBtn').addEventListener('click', async () => {
                    document.body.removeChild(overlay); resolve();
                    await this.manageCategoriesDialog();
                });
                dialog.querySelector('#subCloseBtn').addEventListener('click', close);

                dialog.querySelector('#createSubBtn').addEventListener('click', async () => {
                    const name = await this.showInputDialog(`➕ Нова підкатегорія для "${categoryId}"`, 'Назва підкатегорії:', 'my-sub');
                    if (!name) return;
                    const res = await fetch(`/api/categories/${categoryId}/subcategories`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({name}) });
                    const d = await res.json();
                    if (!res.ok) { this.showToast(d.error || 'Помилка', 'error'); return; }
                    this.showToast(`Підкатегорію "${name}" створено`, 'success');
                    // Якщо зараз активна ця категорія — оновлюємо bar підкатегорій
                    if (this.currentCategory === categoryId) this.loadSubcategories(categoryId);
                    await render();
                });

                dialog.querySelectorAll('.manage-del-btn[data-sub]').forEach(btn => {
                    btn.addEventListener('click', async () => {
                        const sub = btn.dataset.sub;
                        const ok = await this.showConfirmDialog(`Видалити підкатегорію "${sub}"?`, 'Файли повернуться до "general"');
                        if (!ok) return;
                        const res = await fetch(`/api/categories/${categoryId}/subcategories/${sub}`, { method: 'DELETE' });
                        const d = await res.json();
                        if (!res.ok) { this.showToast(d.error || 'Помилка', 'error'); return; }
                        this.showToast(`"${sub}" видалено`, 'success');
                        // Якщо зараз активна ця категорія — оновлюємо bar підкатегорій
                        if (this.currentCategory === categoryId) this.loadSubcategories(categoryId);
                        await render();
                    });
                });
            };

            render();
            overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
        });
    }

    // ── Utility dialogs ──────────────────────────────────
    async showInputDialog(title, label, placeholder = '') {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'duplicate-dialog-overlay';
            const dialog = document.createElement('div');
            dialog.className = 'duplicate-dialog';
            dialog.innerHTML = `
                <div class="duplicate-dialog-header"><h3>${title}</h3></div>
                <div class="duplicate-dialog-content">
                    <p class="duplicate-warning">${label}</p>
                    <div class="rename-input-container">
                        <div class="rename-input-group">
                            <input type="text" class="rename-input" id="utilInput" placeholder="${placeholder}" autocomplete="off">
                        </div>
                    </div>
                </div>
                <div class="duplicate-dialog-actions">
                    <button class="dialog-btn btn-cancel" data-action="cancel">❌ Скасувати</button>
                    <button class="dialog-btn btn-primary" data-action="save">✅ Створити</button>
                </div>
            `;
            overlay.appendChild(dialog);
            document.body.appendChild(overlay);
            const input = dialog.querySelector('#utilInput');
            input.focus();
            const handleSave = () => {
                const val = input.value.trim().toLowerCase().replace(/\s+/g, '-');
                if (!val) { input.classList.add('error-shake'); setTimeout(() => input.classList.remove('error-shake'), 500); return; }
                document.body.removeChild(overlay); resolve(val);
            };
            const handleCancel = () => { document.body.removeChild(overlay); resolve(null); };
            dialog.querySelector('[data-action="save"]').addEventListener('click', handleSave);
            dialog.querySelector('[data-action="cancel"]').addEventListener('click', handleCancel);
            input.addEventListener('keypress', e => { if (e.key === 'Enter') handleSave(); });
            input.addEventListener('keydown', e => { if (e.key === 'Escape') handleCancel(); });
            overlay.addEventListener('click', e => { if (e.target === overlay) handleCancel(); });
        });
    }

    async showConfirmDialog(title, message) {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'duplicate-dialog-overlay';
            const dialog = document.createElement('div');
            dialog.className = 'duplicate-dialog';
            dialog.innerHTML = `
                <div class="duplicate-dialog-header"><h3>⚠️ ${title}</h3></div>
                <div class="duplicate-dialog-content">
                    <p class="duplicate-warning">${message}</p>
                    <p class="delete-warning-text">Цю дію неможливо скасувати!</p>
                </div>
                <div class="duplicate-dialog-actions">
                    <button class="dialog-btn btn-cancel" data-action="cancel">❌ Скасувати</button>
                    <button class="dialog-btn btn-delete" data-action="confirm">🗑️ Підтвердити</button>
                </div>
            `;
            overlay.appendChild(dialog);
            document.body.appendChild(overlay);
            dialog.querySelector('[data-action="confirm"]').addEventListener('click', () => { document.body.removeChild(overlay); resolve(true); });
            dialog.querySelector('[data-action="cancel"]').addEventListener('click', () => { document.body.removeChild(overlay); resolve(false); });
            overlay.addEventListener('click', e => { if (e.target === overlay) { document.body.removeChild(overlay); resolve(false); } });
        });
    }

    async _fetchCategories() {
        try {
            const res = await fetch('/api/categories');
            if (res.ok) return await res.json();
        } catch(e) {}
        return [{id:'document',label:'📄 DOCUMENTS'},{id:'code',label:'💻 CODE'},
                {id:'image',label:'🖼️ IMAGES'},{id:'video',label:'🎥 VIDEO'},
                {id:'audio',label:'🎵 AUDIO'},{id:'archive',label:'📦 ARCHIVES'},{id:'other',label:'📌 OTHER'}];
    }

    // ══════════════════════════════════════════════════════════════
    //  ANALYTICS DASHBOARD
    // ══════════════════════════════════════════════════════════════

    async showAnalytics() {
        const overlay = document.createElement('div');
        overlay.className = 'analytics-overlay';
        overlay.innerHTML = `
            <div class="analytics-panel">
                <div class="analytics-header">
                    <h2 class="analytics-title">⚡ ANALYTICS</h2>
                    <button class="analytics-close" id="analyticsCloseBtn">✕</button>
                </div>
                <div class="analytics-loading" id="analyticsLoading">
                    <div class="analytics-spinner"></div>
                    <span>Завантаження даних...</span>
                </div>
                <div class="analytics-body" id="analyticsBody" style="display:none"></div>
            </div>
        `;
        document.body.appendChild(overlay);
        requestAnimationFrame(() => overlay.classList.add('open'));

        const close = () => {
            overlay.classList.remove('open');
            setTimeout(() => { if (overlay.parentNode) document.body.removeChild(overlay); }, 300);
        };
        overlay.querySelector('#analyticsCloseBtn').addEventListener('click', close);
        overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
        document.addEventListener('keydown', function esc(e) {
            if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); }
        });

        try {
            const res = await fetch('/api/analytics');
            const data = await res.json();
            document.getElementById('analyticsLoading').style.display = 'none';
            const body = document.getElementById('analyticsBody');
            body.style.display = 'grid';
            this._renderAnalytics(body, data);
        } catch(e) {
            document.getElementById('analyticsLoading').innerHTML = '❌ Помилка завантаження даних';
        }
    }

    _renderAnalytics(container, d) {
        if (d.total_files === 0) {
            container.innerHTML = '<div class="analytics-empty">📂 Немає файлів для аналізу</div>';
            return;
        }

        container.innerHTML = `
            <!-- KPI row -->
            <div class="an-kpi-row">
                ${this._kpi('📁', d.total_files, 'Всього файлів')}
                ${this._kpi('💾', this.formatSize(d.total_size), 'Загальний розмір')}
                ${this._kpi('🤖', d.high_confidence_pct + '%', 'AI confidence ≥ 80%')}
                ${this._kpi('🏷️', d.avg_tags_per_file, 'Тегів на файл')}
                ${this._kpi('📂', d.largest_category || '—', 'Найбільша категорія')}
            </div>

            <!-- Row 1: donut + top tags -->
            <div class="an-card" id="anCatCard">
                <div class="an-card-title">📊 Розподіл по категоріях</div>
                <div class="an-donut-wrap">
                    <canvas id="anDonut" width="180" height="180"></canvas>
                    <div class="an-donut-legend" id="anDonutLegend"></div>
                </div>
            </div>
            <div class="an-card" id="anTagsCard">
                <div class="an-card-title">🏷️ Топ теги</div>
                <div class="an-bars" id="anTagBars"></div>
            </div>

            <!-- Row 2: confidence dist + extensions -->
            <div class="an-card" id="anConfCard">
                <div class="an-card-title">🎯 AI Confidence розподіл</div>
                <canvas id="anConf" width="100%" height="180"></canvas>
            </div>
            <div class="an-card" id="anExtCard">
                <div class="an-card-title">📋 Топ розширення</div>
                <div class="an-bars" id="anExtBars"></div>
            </div>

            <!-- Row 3: monthly trend (full width) -->
            <div class="an-card an-full" id="anMonthCard">
                <div class="an-card-title">📈 Завантаження по місяцях</div>
                <canvas id="anMonth" height="120"></canvas>
            </div>

            <!-- Row 4: heatmap (full width) -->
            <div class="an-card an-full" id="anHeatCard">
                <div class="an-card-title">🔥 Heatmap активності — останні 12 тижнів</div>
                <div id="anHeatmap" class="an-heatmap-wrap"></div>
            </div>

            <!-- Row 5: size by category -->
            <div class="an-card an-full" id="anSizeCard">
                <div class="an-card-title">⚖️ Розмір файлів по категоріях</div>
                <div class="an-bars" id="anSizeBars"></div>
            </div>
        `;

        requestAnimationFrame(() => {
            this._drawDonut(d.categories_dist);
            this._drawTagBars(d.top_tags);
            this._drawConfidenceBars(d.confidence_dist);
            this._drawExtBars(d.top_extensions);
            this._drawMonthChart(d.uploads_by_month);
            this._drawHeatmap(d.upload_heatmap);
            this._drawSizeBars(d.size_by_category);
        });
    }

    _kpi(icon, value, label) {
        return `<div class="an-kpi"><div class="an-kpi-icon">${icon}</div>
            <div class="an-kpi-val">${value}</div><div class="an-kpi-label">${label}</div></div>`;
    }

    _catColor(cat, idx) {
        const palette = {
            document: '#00e5ff', code: '#ff6b6b', image: '#ffd93d',
            video: '#6bcb77', audio: '#c77dff', archive: '#f4845f', other: '#adb5bd'
        };
        const fallbacks = ['#00e5ff','#ff6b6b','#ffd93d','#6bcb77','#c77dff','#f4845f','#a8dadc'];
        return palette[cat] || fallbacks[idx % fallbacks.length];
    }

    _drawDonut(cats) {
        const canvas = document.getElementById('anDonut');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const cx = 90, cy = 90, r = 72, inner = 44;
        const total = cats.reduce((s, c) => s + c.count, 0);
        let angle = -Math.PI / 2;
        const legend = document.getElementById('anDonutLegend');
        legend.innerHTML = '';

        cats.forEach((c, i) => {
            const slice = (c.count / total) * Math.PI * 2;
            const color = this._catColor(c.category, i);
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.arc(cx, cy, r, angle, angle + slice);
            ctx.closePath();
            ctx.fillStyle = color;
            ctx.fill();
            // Inner hole
            ctx.beginPath();
            ctx.arc(cx, cy, inner, 0, Math.PI * 2);
            ctx.fillStyle = 'var(--bg, #0a0a0f)';
            ctx.fill();
            angle += slice;
            // Legend
            legend.innerHTML += `<div class="an-legend-item">
                <span class="an-legend-dot" style="background:${color}"></span>
                <span>${c.category}</span>
                <span class="an-legend-pct">${c.pct}%</span>
            </div>`;
        });

        // Center text
        ctx.fillStyle = 'rgba(255,255,255,0.9)';
        ctx.font = 'bold 18px monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(total, cx, cy);
    }

    _drawTagBars(tags) {
        const el = document.getElementById('anTagBars');
        if (!tags.length) { el.innerHTML = '<span class="an-empty">Немає тегів</span>'; return; }
        const max = tags[0].count;
        el.innerHTML = tags.map((t, i) => `
            <div class="an-bar-row">
                <span class="an-bar-label">#${t.tag}</span>
                <div class="an-bar-track">
                    <div class="an-bar-fill" style="width:${t.count/max*100}%;background:${this._catColor(t.tag, i)};
                        animation:anBarGrow .6s ${i*0.05}s both"></div>
                </div>
                <span class="an-bar-val">${t.count}</span>
            </div>`).join('');
    }

    _drawConfidenceBars(dist) {
        const canvas = document.getElementById('anConf');
        if (!canvas) return;
        const parent = canvas.closest('.an-card');
        const w = parent ? parent.clientWidth - 32 : 340;
        canvas.width = w;
        const ctx = canvas.getContext('2d');
        const h = 160, pad = 28, barW = Math.floor((w - pad * 2) / 10) - 2;
        const max = Math.max(...dist.map(d => d.count), 1);
        const accent = '#00e5ff';

        dist.forEach((d, i) => {
            const x = pad + i * ((w - pad * 2) / 10);
            const bh = d.count / max * (h - 40);
            const y = h - 20 - bh;
            // Bar gradient
            const grad = ctx.createLinearGradient(0, y, 0, h - 20);
            grad.addColorStop(0, accent);
            grad.addColorStop(1, 'rgba(0,229,255,0.2)');
            ctx.fillStyle = grad;
            ctx.beginPath();
            ctx.roundRect(x + 1, y, barW, bh, [3, 3, 0, 0]);
            ctx.fill();
            // X label
            ctx.fillStyle = 'rgba(255,255,255,0.4)';
            ctx.font = '9px monospace';
            ctx.textAlign = 'center';
            ctx.fillText(d.range.split('-')[0], x + barW / 2 + 1, h - 6);
            // Count on top
            if (d.count > 0) {
                ctx.fillStyle = 'rgba(255,255,255,0.7)';
                ctx.font = '10px monospace';
                ctx.fillText(d.count, x + barW / 2 + 1, y - 4);
            }
        });
        // X axis
        ctx.strokeStyle = 'rgba(255,255,255,0.15)';
        ctx.beginPath(); ctx.moveTo(pad, h - 20); ctx.lineTo(w - pad, h - 20); ctx.stroke();
    }

    _drawExtBars(exts) {
        const el = document.getElementById('anExtBars');
        if (!exts.length) { el.innerHTML = '<span class="an-empty">—</span>'; return; }
        const max = exts[0].count;
        el.innerHTML = exts.map((e, i) => `
            <div class="an-bar-row">
                <span class="an-bar-label">.${e.ext}</span>
                <div class="an-bar-track">
                    <div class="an-bar-fill" style="width:${e.count/max*100}%;background:${this._catColor(e.ext, i+3)};
                        animation:anBarGrow .6s ${i*0.05}s both"></div>
                </div>
                <span class="an-bar-val">${e.count}</span>
            </div>`).join('');
    }

    _drawMonthChart(months) {
        const canvas = document.getElementById('anMonth');
        if (!canvas) return;
        const parent = canvas.closest('.an-card');
        const w = parent ? parent.clientWidth - 32 : 600;
        canvas.width = w;
        const ctx = canvas.getContext('2d');
        const h = 120, pad = 36, pts = months.length;
        const max = Math.max(...months.map(m => m.count), 1);
        const stepX = (w - pad * 2) / (pts - 1 || 1);

        // Grid lines
        ctx.strokeStyle = 'rgba(255,255,255,0.07)';
        for (let i = 0; i <= 4; i++) {
            const y = pad + ((h - pad * 2) / 4) * i;
            ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(w - pad, y); ctx.stroke();
        }

        // Area fill
        ctx.beginPath();
        months.forEach((m, i) => {
            const x = pad + i * stepX;
            const y = h - pad - (m.count / max) * (h - pad * 2);
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        const lastX = pad + (pts - 1) * stepX;
        ctx.lineTo(lastX, h - pad);
        ctx.lineTo(pad, h - pad);
        ctx.closePath();
        const grad = ctx.createLinearGradient(0, pad, 0, h - pad);
        grad.addColorStop(0, 'rgba(0,229,255,0.35)');
        grad.addColorStop(1, 'rgba(0,229,255,0.02)');
        ctx.fillStyle = grad;
        ctx.fill();

        // Line
        ctx.beginPath();
        months.forEach((m, i) => {
            const x = pad + i * stepX;
            const y = h - pad - (m.count / max) * (h - pad * 2);
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.strokeStyle = '#00e5ff';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Dots + labels
        months.forEach((m, i) => {
            const x = pad + i * stepX;
            const y = h - pad - (m.count / max) * (h - pad * 2);
            ctx.beginPath();
            ctx.arc(x, y, 4, 0, Math.PI * 2);
            ctx.fillStyle = '#00e5ff';
            ctx.fill();
            ctx.fillStyle = 'rgba(255,255,255,0.45)';
            ctx.font = '10px monospace';
            ctx.textAlign = 'center';
            ctx.fillText(m.month.slice(0, 3), x, h - 4);
            if (m.count > 0) {
                ctx.fillStyle = 'rgba(255,255,255,0.7)';
                ctx.fillText(m.count, x, y - 10);
            }
        });
    }

    _drawHeatmap(days) {
        const wrap = document.getElementById('anHeatmap');
        if (!wrap) return;
        const max = Math.max(...days.map(d => d.count), 1);
        const dayNames = ['Нд','Пн','Вт','Ср','Чт','Пт','Сб'];

        let html = '<div class="an-heatmap-grid">';
        // Day labels column
        html += '<div class="an-heatmap-days">';
        dayNames.forEach(d => { html += `<span>${d}</span>`; });
        html += '</div>';

        // 12 weeks × 7 days
        for (let w = 0; w < 12; w++) {
            html += '<div class="an-heatmap-week">';
            for (let d = 0; d < 7; d++) {
                const idx = w * 7 + d;
                const day = days[idx];
                const intensity = day ? day.count / max : 0;
                const alpha = day && day.count > 0 ? Math.max(0.15, intensity) : 0.04;
                const tip = day ? `${day.date}: ${day.count}` : '';
                html += `<div class="an-heatmap-cell" 
                    style="background:rgba(0,229,255,${alpha.toFixed(2)})"
                    title="${tip}"></div>`;
            }
            html += '</div>';
        }
        html += '</div>';
        wrap.innerHTML = html;
    }

    _drawSizeBars(sizes) {
        const el = document.getElementById('anSizeBars');
        if (!sizes.length) { el.innerHTML = '<span class="an-empty">—</span>'; return; }
        const max = sizes[0].total_size;
        el.innerHTML = sizes.map((s, i) => `
            <div class="an-bar-row">
                <span class="an-bar-label">${s.category}</span>
                <div class="an-bar-track">
                    <div class="an-bar-fill" style="width:${s.total_size/max*100}%;background:${this._catColor(s.category,i)};
                        animation:anBarGrow .6s ${i*0.06}s both"></div>
                </div>
                <span class="an-bar-val">${this.formatSize(s.avg_size)} avg</span>
            </div>`).join('');
    }

    // ══════════════════════════════════════════════════════════════
    //  SMART ALERTS
    // ══════════════════════════════════════════════════════════════

    // ══════════════════════════════════════════════════════════════
    //  SMART ALERTS — стан (прочитано/видалено) зберігається в localStorage
    // ══════════════════════════════════════════════════════════════

    /* Storage schema: { [alertId]: { r: 1, d: 1 } }
       r = read (прочитано), d = dismissed (видалено з панелі)   */
    _aState()   { try { return JSON.parse(localStorage.getItem('cdnx_alerts') || '{}'); } catch { return {}; } }
    _aSave(s)   { try { localStorage.setItem('cdnx_alerts', JSON.stringify(s)); } catch {} }
    _aIsRead(id)      { return !!this._aState()[id]?.r; }
    _aIsDismissed(id) { return !!this._aState()[id]?.d; }
    _aSetRead(id)      { const s=this._aState(); s[id]={...(s[id]||{}),r:1};    this._aSave(s); }
    _aSetDismissed(id) { const s=this._aState(); s[id]={r:1,d:1};               this._aSave(s); }
    _aMarkAllRead()    { const s=this._aState(); (this._alertsData||[]).forEach(a=>{s[a.id]={...(s[a.id]||{}),r:1};}); this._aSave(s); }
    _aDismissAll()     { const s=this._aState(); (this._alertsData||[]).forEach(a=>{s[a.id]={r:1,d:1};}); this._aSave(s); }
    // Прибираємо з localStorage записи про алерти яких сервер більше не повертає
    _aGc() {
        const ids = new Set((this._alertsData||[]).map(a=>a.id));
        const s   = this._aState();
        this._aSave(Object.fromEntries(Object.entries(s).filter(([k])=>ids.has(k))));
    }
    _aVisible() { return (this._alertsData||[]).filter(a => !this._aIsDismissed(a.id)); }
    _aUnread()  { return this._aVisible().filter(a => !this._aIsRead(a.id)); }

    async alertsLoad() {
        try {
            const data = await fetch('/api/alerts').then(r => r.json());
            this._alertsData = data;
            this._aGc();
            this._alertsUpdateBell();
        } catch(e) { console.error('Alerts fetch error', e); }
    }

    _alertsUpdateBell() {
        const btn   = document.getElementById('alertsBellBtn');
        const badge = document.getElementById('alertsBadge');
        if (!btn || !badge) return;

        const visible = this._aVisible();
        const unread  = this._aUnread();
        const n       = unread.length;

        badge.textContent = n > 99 ? '99+' : String(n);
        badge.style.display = n ? 'flex' : 'none';

        const hasCrit = unread.some(a => a.severity === 'error');
        const hasWarn = unread.some(a => a.severity === 'warning');
        btn.className = 'bell-btn ' + (
            !visible.length ? 'bell-ok'    :
            !n              ? 'bell-ok'    :
            hasCrit         ? 'bell-error' :
            hasWarn         ? 'bell-warn'  : 'bell-info'
        );
        btn.title = n
            ? `Smart Alerts: ${n} непрочитаних — клік для перегляду`
            : visible.length
                ? `Smart Alerts: усі прочитані (${visible.length})`
                : 'Smart Alerts — все гаразд ✅';
    }

    alertsOpen() {
        const existing = document.getElementById('alertsOverlay');
        if (existing) { this._alertsClose(existing); return; }

        const visible = this._aVisible();
        const unread  = this._aUnread();

        const SEV = {
            error:   { label: '❌ Критично',    cls: 'ac-error' },
            warning: { label: '⚠️ Увага',        cls: 'ac-warn'  },
            info:    { label: 'ℹ️ Рекомендація', cls: 'ac-info'  },
        };

        // Summary chips
        const errN  = visible.filter(a => a.severity === 'error').length;
        const warnN = visible.filter(a => a.severity === 'warning').length;
        const infN  = visible.filter(a => a.severity === 'info').length;
        const chips = [
            errN  && `<span class="al-chip al-chip-error">❌ ${errN} критичних</span>`,
            warnN && `<span class="al-chip al-chip-warn">⚠️ ${warnN} попереджень</span>`,
            infN  && `<span class="al-chip al-chip-info">ℹ️ ${infN} рекомендацій</span>`,
        ].filter(Boolean).join('');

        // Cards
        const cardsHtml = visible.length === 0
            ? `<div class="al-empty">
                 <div class="al-empty-icon">✅</div>
                 <strong>Усе гаразд!</strong>
                 <span>Проблем не знайдено або всі сповіщення видалено.</span>
               </div>`
            : visible.map((a, i) => {
                const isRead = this._aIsRead(a.id);
                return `
                <div class="al-card ${SEV[a.severity]?.cls||''}${isRead?' al-card-read':''}" data-id="${a.id}">
                  <div class="al-card-top">
                    <span class="al-card-icon">${a.icon}</span>
                    <div class="al-card-meta">
                      <span class="al-card-title">${this._esc(a.title)}</span>
                      <span class="al-sev-label ${SEV[a.severity]?.cls||''}">${SEV[a.severity]?.label||''}</span>
                    </div>
                    <span class="al-card-count">${a.count}</span>
                    <div class="al-card-actions-inline">
                      <button class="al-btn-read${isRead?' al-btn-read-done':''}"
                              data-id="${a.id}" title="${isRead?'Прочитано':'Позначити прочитаним'}"
                              ${isRead?'disabled':''}>✓</button>
                      <button class="al-btn-dismiss" data-id="${a.id}" title="Видалити сповіщення">✕</button>
                    </div>
                  </div>
                  <p class="al-card-desc">${this._esc(a.description)}</p>
                  <div class="al-card-rec"><span class="al-rec-bullet">💡</span>${this._esc(a.recommendation)}</div>
                  ${a.file_ids?.length
                    ? `<button class="al-show-btn" data-idx="${i}">🔍 Показати файли (${a.count})</button>`
                    : ''}
                </div>`;
              }).join('');

        const overlay = document.createElement('div');
        overlay.id = 'alertsOverlay';
        overlay.className = 'al-overlay';
        overlay.innerHTML = `
          <div class="al-panel">
            <div class="al-header">
              <div class="al-header-left">
                <span>🔔</span>
                <span class="al-header-title">SMART ALERTS</span>
                ${visible.length ? `<span class="al-header-cnt">${visible.length}</span>` : ''}
              </div>
              <div class="al-header-right">
                ${unread.length >= 2
                  ? `<button class="al-hdr-btn" id="alMarkAll">✓ Всі прочитані</button>` : ''}
                ${visible.length
                  ? `<button class="al-hdr-btn al-hdr-btn-danger" id="alDismissAll">🗑 Видалити всі</button>` : ''}
                <button class="al-icon-btn" id="alertsRefreshBtn" title="Оновити дані">↻</button>
                <button class="al-icon-btn al-icon-btn-close" id="alertsCloseBtn">✕</button>
              </div>
            </div>
            ${visible.length ? `<div class="al-summary">${chips}</div>` : ''}
            <div class="al-body" id="alertsBody">${cardsHtml}</div>
          </div>`;

        document.body.appendChild(overlay);
        requestAnimationFrame(() => overlay.classList.add('open'));

        // ── Кнопки хедера ─────────────────────────────────────────
        overlay.querySelector('#alertsCloseBtn')
               .addEventListener('click', () => this._alertsClose(overlay));
        overlay.addEventListener('click', e => {
            if (e.target === overlay) this._alertsClose(overlay);
        });

        overlay.querySelector('#alertsRefreshBtn')
               .addEventListener('click', async () => {
                   const b = overlay.querySelector('#alertsRefreshBtn');
                   b.style.opacity = '0.3';
                   await this.alertsLoad();
                   b.style.opacity = '';
                   this._alertsClose(overlay);
                   setTimeout(() => this.alertsOpen(), 300);
               });

        overlay.querySelector('#alMarkAll')
               ?.addEventListener('click', () => {
                   this._aMarkAllRead();
                   this._alertsUpdateBell();
                   overlay.querySelectorAll('.al-card').forEach(c => c.classList.add('al-card-read'));
                   overlay.querySelectorAll('.al-btn-read:not([disabled])').forEach(b => {
                       b.classList.add('al-btn-read-done'); b.disabled = true; b.title = 'Прочитано';
                   });
                   overlay.querySelector('#alMarkAll')?.remove();
               });

        overlay.querySelector('#alDismissAll')
               ?.addEventListener('click', () => {
                   this._aDismissAll();
                   this._alertsUpdateBell();
                   this._alertsClose(overlay);
                   setTimeout(() => this.alertsOpen(), 300);
               });

        // ── Кнопки на кожній картці ────────────────────────────────
        overlay.querySelectorAll('.al-btn-read').forEach(btn => {
            btn.addEventListener('click', e => {
                e.stopPropagation();
                this._aSetRead(btn.dataset.id);
                this._alertsUpdateBell();
                const card = btn.closest('.al-card');
                card.classList.add('al-card-read');
                btn.classList.add('al-btn-read-done');
                btn.disabled = true;
                btn.title = 'Прочитано';
                if (!this._aUnread().length) overlay.querySelector('#alMarkAll')?.remove();
            });
        });

        overlay.querySelectorAll('.al-btn-dismiss').forEach(btn => {
            btn.addEventListener('click', e => {
                e.stopPropagation();
                this._aSetDismissed(btn.dataset.id);
                this._alertsUpdateBell();
                const card = btn.closest('.al-card');
                // Анімація зникнення
                card.style.transition = 'opacity .22s, max-height .28s .05s, margin .28s .05s';
                card.style.overflow   = 'hidden';
                card.style.maxHeight  = card.scrollHeight + 'px';
                card.style.opacity    = '0';
                requestAnimationFrame(() => { card.style.maxHeight = '0'; card.style.marginBottom = '0'; });
                setTimeout(() => {
                    card.remove();
                    this._alertsHandleBodyEmpty(overlay);
                }, 340);
            });
        });

        overlay.querySelectorAll('.al-show-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const a = visible[parseInt(btn.dataset.idx)];
                if (!a?.file_ids?.length) return;
                this._aSetRead(a.id);
                this._alertsClose(overlay);
                this._alertsHighlightFiles(a);
            });
        });
    }

    _alertsHandleBodyEmpty(overlay) {
        const body = overlay.querySelector('#alertsBody');
        if (!body || body.querySelector('.al-card')) return;
        body.innerHTML = `
            <div class="al-empty">
              <div class="al-empty-icon">🗑️</div>
              <strong>Усі видалено</strong>
              <span>Натисніть ↻ щоб перевірити наявність нових.</span>
            </div>`;
        overlay.querySelector('.al-header-cnt')?.remove();
        overlay.querySelector('#alMarkAll')?.remove();
        overlay.querySelector('#alDismissAll')?.remove();
    }

    _alertsClose(overlay) {
        overlay.classList.remove('open');
        setTimeout(() => overlay.remove(), 280);
    }

    _alertsHighlightFiles(alert) {
        this.currentCategory = 'all';
        this.currentSubcategory = null;
        document.querySelectorAll('.cat-tab').forEach(t =>
            t.classList.toggle('active', t.dataset.category === 'all'));
        this.loadFiles().then(() => {
            this.enableBulkMode();
            alert.file_ids.forEach(id => this.selectedFileIds.add(id));
            this.renderFiles();
            this.updateBulkToolbar();
            this.showToast(`🔔 Виділено ${alert.file_ids.length} файл(ів): ${alert.title}`, 'info');
        });
    }

    _setupAlertsKeyClose() {
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') {
                const ov = document.getElementById('alertsOverlay');
                if (ov) this._alertsClose(ov);
            }
        });
    }


}
// Initialize app
let app;
document.addEventListener('DOMContentLoaded', () => {
    console.log('📋 DOM loaded, creating app instance...');
    try {
        app = new CyberDataNexus();
        app._setupAlertsKeyClose();
        console.log('✅ App instance created:', app);
    } catch (error) {
        console.error('❌ Error creating app:', error);
    }
});

console.log('📄 App.js file loaded completely');