/**
 * VNStock News Portal - Interactive Client Logic
 */

document.addEventListener('DOMContentLoaded', () => {
  // --- Theme Management ---
  const themeToggleBtn = document.getElementById('themeToggleBtn');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const savedTheme = localStorage.getItem('vnstock_theme') || (prefersDark ? 'dark' : 'light');

  function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('vnstock_theme', theme);
    if (themeToggleBtn) {
      themeToggleBtn.innerHTML = theme === 'dark'
        ? `<svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" /></svg>`
        : `<svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" /></svg>`;
    }
  }

  setTheme(savedTheme);

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme') || 'dark';
      setTheme(current === 'dark' ? 'light' : 'dark');
    });
  }

  // --- Search & Filters ---
  const searchInput = document.getElementById('searchInput');
  const clearSearchBtn = document.getElementById('clearSearchBtn');
  const dateFilterSelect = document.getElementById('dateFilterSelect');
  const sourceTabs = document.querySelectorAll('.source-tab');

  let debounceTimer = null;

  function applyFilter(params = {}) {
    const url = new URL(window.location.href);
    Object.keys(params).forEach(k => {
      if (params[k] !== undefined && params[k] !== null && params[k] !== '') {
        url.searchParams.set(k, params[k]);
      } else {
        url.searchParams.delete(k);
      }
    });
    // Reset về trang 1 khi đổi bộ lọc
    if (!('page' in params)) {
      url.searchParams.set('page', '1');
    }
    window.location.href = url.toString();
  }

  if (searchInput) {
    // Hiện nút Clear nếu có nội dung
    if (searchInput.value) {
      clearSearchBtn.classList.add('active');
    }

    searchInput.addEventListener('input', (e) => {
      if (e.target.value) {
        clearSearchBtn.classList.add('active');
      } else {
        clearSearchBtn.classList.remove('active');
      }

      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        applyFilter({ q: e.target.value.trim() });
      }, 600);
    });

    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        clearTimeout(debounceTimer);
        applyFilter({ q: e.target.value.trim() });
      }
    });
  }

  if (clearSearchBtn) {
    clearSearchBtn.addEventListener('click', () => {
      if (searchInput) {
        searchInput.value = '';
        clearSearchBtn.classList.remove('active');
        applyFilter({ q: '' });
      }
    });
  }

  // Bấm phím tắt '/' để focus vào ô tìm kiếm
  window.addEventListener('keydown', (e) => {
    if (e.key === '/' && document.activeElement !== searchInput) {
      e.preventDefault();
      searchInput?.focus();
    }
  });

  if (dateFilterSelect) {
    dateFilterSelect.addEventListener('change', (e) => {
      applyFilter({ date: e.target.value });
    });
  }

  sourceTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const source = tab.getAttribute('data-source');
      applyFilter({ source: source === 'all' ? '' : source });
    });
  });

  // --- Modal Reader ---
  const modalBackdrop = document.getElementById('articleModal');
  const modalCloseBtn = document.getElementById('modalCloseBtn');
  const modalBody = document.getElementById('modalBody');
  const modalSourceBadge = document.getElementById('modalSourceBadge');
  const modalArticleOriginalBtn = document.getElementById('modalArticleOriginalBtn');
  const modalCopyLinkBtn = document.getElementById('modalCopyLinkBtn');

  let currentArticleUrl = '';

  window.openArticleModal = async function(articleId) {
    if (!modalBackdrop) return;

    modalBackdrop.classList.add('open');
    document.body.style.overflow = 'hidden';

    // Loading skeleton
    modalBody.innerHTML = `
      <div class="spinner"></div>
      <p style="text-align: center; color: var(--text-muted);">Đang tải nội dung bài viết...</p>
    `;

    try {
      const res = await fetch(`/api/articles/${articleId}`);
      if (!res.ok) throw new Error('Không thể tải bài viết');
      const article = await res.json();

      currentArticleUrl = article.url;
      if (modalArticleOriginalBtn) {
        modalArticleOriginalBtn.href = article.url;
      }

      if (modalSourceBadge) {
        modalSourceBadge.textContent = article.source_name || article.source;
        modalSourceBadge.style.color = article.source_color || '#3b82f6';
        modalSourceBadge.style.backgroundColor = article.source_badge_bg || 'rgba(59, 130, 246, 0.15)';
        modalSourceBadge.style.borderColor = article.source_badge_border || 'rgba(59, 130, 246, 0.35)';
      }

      // Render tags
      let tagsHtml = '';
      if (article.tags && article.tags.length > 0) {
        tagsHtml = `
          <div class="modal-tags-section">
            <div class="modal-tags-title">Từ khóa & Mã chứng khoán</div>
            <div class="card-tags">
              ${article.tags.map(t => `<span class="tag-chip" onclick="searchTag('${t}')">#${t}</span>`).join('')}
            </div>
          </div>
        `;
      }

      // Render related articles
      let relatedHtml = '';
      if (article.related && article.related.length > 0) {
        relatedHtml = `
          <div class="modal-related-section">
            <div class="modal-tags-title">Tin cùng chuyên mục & nguồn</div>
            <div class="related-grid">
              ${article.related.map(rel => `
                <div class="related-card" onclick="openArticleModal(${rel.id})">
                  <div class="related-card-title">${rel.title}</div>
                  <div style="font-size: 0.75rem; color: var(--text-muted); display: flex; justify-content: space-between;">
                    <span style="color: ${rel.source_color}">${rel.source_name}</span>
                    <span>${rel.published_at_relative || ''}</span>
                  </div>
                </div>
              `).join('')}
            </div>
          </div>
        `;
      }

      modalBody.innerHTML = `
        <h1 class="article-title">${article.title}</h1>
        <div class="modal-article-info">
          <span>🕒 ${article.published_at_formatted || article.published_at_relative}</span>
          ${article.author ? `<span>✍️ ${article.author}</span>` : ''}
          ${article.original_source ? `<span>📰 Nguồn: ${article.original_source}</span>` : ''}
          ${article.word_count ? `<span>📊 ${article.word_count} từ</span>` : ''}
        </div>
        ${article.sapo ? `<div class="modal-sapo">${article.sapo}</div>` : ''}
        <div class="article-rendered-content">
          ${article.rendered_html || `<p>${article.content_text || ''}</p>`}
        </div>
        ${tagsHtml}
        ${relatedHtml}
      `;

    } catch (err) {
      modalBody.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">⚠️</div>
          <p>Có lỗi xảy ra khi tải bài viết. Vui lòng thử lại sau.</p>
        </div>
      `;
    }
  };

  function closeModal() {
    if (!modalBackdrop) return;
    modalBackdrop.classList.remove('open');
    document.body.style.overflow = '';
  }

  if (modalCloseBtn) {
    modalCloseBtn.addEventListener('click', closeModal);
  }

  if (modalBackdrop) {
    modalBackdrop.addEventListener('click', (e) => {
      if (e.target === modalBackdrop) {
        closeModal();
      }
    });
  }

  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modalBackdrop?.classList.contains('open')) {
      closeModal();
    }
  });

  window.searchTag = function(tag) {
    closeModal();
    applyFilter({ q: tag });
  };

  // Toast Notification
  function showToast(message) {
    let toast = document.getElementById('toastMsg');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'toastMsg';
      toast.className = 'toast-msg';
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add('show');
    setTimeout(() => {
      toast.classList.remove('show');
    }, 2500);
  }

  if (modalCopyLinkBtn) {
    modalCopyLinkBtn.addEventListener('click', () => {
      if (currentArticleUrl) {
        navigator.clipboard.writeText(currentArticleUrl).then(() => {
          showToast('Đã sao chép liên kết bài viết gốc!');
        });
      }
    });
  }

  // --- Manual Refresh Button ---
  const refreshBtn = document.getElementById('refreshBtn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      refreshBtn.style.transform = 'rotate(180deg)';
      setTimeout(() => {
        window.location.reload();
      }, 200);
    });
  }
});
