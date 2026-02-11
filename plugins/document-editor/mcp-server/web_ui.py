"""
Web UI Generator for Interactive Document Editor

Generates two types of self-contained HTML files:
1. Comment collection UI - users click paragraphs and enter editing instructions
2. Review UI - users Accept/Reject AI-suggested changes with diff view
"""

import json
import re
from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class Paragraph:
    """Represents a paragraph block in the markdown content."""
    index: int
    text: str       # plain text content
    raw: str        # original markdown
    block_type: str # heading, paragraph, list, code, blockquote, hr


def parse_markdown_paragraphs(content: str) -> List[Paragraph]:
    """
    Parse markdown content into paragraph-level blocks.
    Groups consecutive lines into logical blocks separated by blank lines.
    """
    paragraphs = []
    lines = content.split('\n')
    current_block: list[str] = []
    current_type = "paragraph"
    in_code_block = False
    idx = 0

    def flush():
        nonlocal current_block, current_type, idx
        if not current_block:
            return
        raw = '\n'.join(current_block)
        text = raw
        # Strip markdown formatting for plain text
        if current_type == "heading":
            text = re.sub(r'^#+\s*', '', text)
        elif current_type == "code":
            # Remove fence lines
            code_lines = current_block[:]
            if code_lines and code_lines[0].startswith('```'):
                code_lines = code_lines[1:]
            if code_lines and code_lines[-1].startswith('```'):
                code_lines = code_lines[:-1]
            text = '\n'.join(code_lines)
        elif current_type == "blockquote":
            text = re.sub(r'^>\s?', '', text, flags=re.MULTILINE)

        paragraphs.append(Paragraph(
            index=idx,
            text=text.strip(),
            raw=raw,
            block_type=current_type
        ))
        idx += 1
        current_block = []
        current_type = "paragraph"

    for line in lines:
        stripped = line.strip()

        # Code block toggle
        if stripped.startswith('```'):
            if in_code_block:
                current_block.append(line)
                in_code_block = False
                flush()
                continue
            else:
                flush()
                in_code_block = True
                current_type = "code"
                current_block.append(line)
                continue

        if in_code_block:
            current_block.append(line)
            continue

        # Blank line = block separator
        if stripped == '':
            flush()
            continue

        # Horizontal rule
        if re.match(r'^(-{3,}|\*{3,}|_{3,})$', stripped):
            flush()
            current_block.append(line)
            current_type = "hr"
            flush()
            continue

        # Heading
        if re.match(r'^#{1,6}\s', stripped):
            flush()
            current_block.append(line)
            current_type = "heading"
            flush()
            continue

        # List item (start of new list or continuation)
        if re.match(r'^(\s*[-*+]|\s*\d+\.)\s', line):
            if current_type != "list":
                flush()
                current_type = "list"
            current_block.append(line)
            continue

        # Blockquote
        if stripped.startswith('>'):
            if current_type != "blockquote":
                flush()
                current_type = "blockquote"
            current_block.append(line)
            continue

        # Regular paragraph text
        if current_type not in ("paragraph",):
            flush()
        current_block.append(line)
        current_type = "paragraph"

    # Don't forget remaining content
    flush()

    return paragraphs


def _escape_for_json_in_template(s: str) -> str:
    """Escape a string for safe embedding in an HTML template's JavaScript."""
    return json.dumps(s)


def generate_comment_html(title: str, content: str, paragraphs: List[Paragraph], server_port: int) -> str:
    """
    Generate HTML for Phase 1: Comment Collection UI.

    Users see the rendered markdown with clickable paragraphs.
    Clicking a paragraph opens a sidebar form to enter editing instructions.
    """
    paragraphs_json = json.dumps([
        {
            "index": p.index,
            "text": p.text,
            "raw": p.raw,
            "block_type": p.block_type
        }
        for p in paragraphs
    ], ensure_ascii=False)

    content_json = json.dumps(content, ensure_ascii=False)

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Document Editor</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root {{
            --bg-primary: #0d1117;
            --bg-secondary: #161b22;
            --bg-tertiary: #21262d;
            --bg-card: #1c2128;
            --text-primary: #e6edf3;
            --text-secondary: #8b949e;
            --text-muted: #6e7681;
            --accent: #58a6ff;
            --accent-hover: #79b8ff;
            --success: #3fb950;
            --warning: #d29922;
            --danger: #f85149;
            --border: #30363d;
            --highlight-bg: rgba(56, 139, 253, 0.15);
            --comment-indicator: #d29922;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            min-height: 100vh;
        }}

        .layout {{
            display: flex;
            min-height: 100vh;
        }}

        .main-content {{
            flex: 1;
            max-width: 900px;
            padding: 2rem;
            overflow-y: auto;
        }}

        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--border);
        }}

        header h1 {{
            font-size: 1.5rem;
            font-weight: 600;
        }}

        .badge {{
            background: var(--bg-tertiary);
            padding: 0.25rem 0.75rem;
            border-radius: 12px;
            font-size: 0.8rem;
            color: var(--text-secondary);
        }}

        .description {{
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin-bottom: 1.5rem;
        }}

        /* Document paragraphs */
        .document-container {{
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
        }}

        .paragraph-block {{
            padding: 12px 20px;
            border-bottom: 1px solid transparent;
            cursor: pointer;
            position: relative;
            transition: background 0.15s, border-color 0.15s;
        }}

        .paragraph-block:hover {{
            background: var(--bg-tertiary);
        }}

        .paragraph-block.selected {{
            background: var(--highlight-bg);
            border-left: 3px solid var(--accent);
            padding-left: 17px;
        }}

        .paragraph-block.has-comment {{
            border-left: 3px solid var(--comment-indicator);
            padding-left: 17px;
        }}

        .paragraph-block.has-comment.selected {{
            border-left: 3px solid var(--accent);
        }}

        .paragraph-index {{
            position: absolute;
            right: 12px;
            top: 12px;
            font-size: 0.7rem;
            color: var(--text-muted);
            background: var(--bg-tertiary);
            padding: 2px 6px;
            border-radius: 4px;
            opacity: 0;
            transition: opacity 0.15s;
        }}

        .paragraph-block:hover .paragraph-index {{
            opacity: 1;
        }}

        .comment-badge {{
            position: absolute;
            right: 12px;
            top: 50%;
            transform: translateY(-50%);
            width: 24px;
            height: 24px;
            background: var(--comment-indicator);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            color: white;
        }}

        /* Markdown rendered styles inside paragraph blocks */
        .paragraph-block h1,
        .paragraph-block h2,
        .paragraph-block h3,
        .paragraph-block h4 {{
            margin: 0;
            line-height: 1.4;
        }}
        .paragraph-block h1 {{ font-size: 1.8em; }}
        .paragraph-block h2 {{ font-size: 1.4em; }}
        .paragraph-block h3 {{ font-size: 1.17em; }}
        .paragraph-block p {{ margin: 0; }}
        .paragraph-block ul, .paragraph-block ol {{
            margin: 0;
            padding-left: 1.5em;
        }}
        .paragraph-block pre {{
            background: var(--bg-tertiary);
            padding: 12px;
            border-radius: 6px;
            overflow-x: auto;
            margin: 0;
        }}
        .paragraph-block code {{
            background: var(--bg-tertiary);
            padding: 0.15em 0.35em;
            border-radius: 4px;
            font-family: 'SF Mono', Monaco, Consolas, monospace;
            font-size: 85%;
        }}
        .paragraph-block pre code {{
            background: none;
            padding: 0;
        }}
        .paragraph-block blockquote {{
            border-left: 4px solid var(--border);
            padding-left: 16px;
            color: var(--text-secondary);
            margin: 0;
        }}
        .paragraph-block hr {{
            border: none;
            border-top: 1px solid var(--border);
            margin: 8px 0;
        }}

        /* Sidebar */
        .sidebar {{
            width: 380px;
            background: var(--bg-secondary);
            border-left: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            height: 100vh;
            position: sticky;
            top: 0;
        }}

        .sidebar-header {{
            padding: 16px 20px;
            border-bottom: 1px solid var(--border);
            font-weight: 600;
            font-size: 0.9rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .sidebar-content {{
            flex: 1;
            overflow-y: auto;
            padding: 16px;
        }}

        /* Comment form */
        .comment-form {{
            display: none;
        }}

        .comment-form.active {{
            display: block;
        }}

        .selected-text-preview {{
            background: var(--bg-primary);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 12px;
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-bottom: 16px;
            max-height: 120px;
            overflow-y: auto;
            white-space: pre-wrap;
            font-family: 'SF Mono', Monaco, Consolas, monospace;
        }}

        .form-label {{
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--text-secondary);
            text-transform: uppercase;
            margin-bottom: 8px;
            display: block;
        }}

        .comment-textarea {{
            width: 100%;
            min-height: 100px;
            padding: 12px;
            background: var(--bg-primary);
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text-primary);
            font-size: 0.875rem;
            resize: vertical;
            font-family: inherit;
            line-height: 1.5;
        }}

        .comment-textarea:focus {{
            outline: none;
            border-color: var(--accent);
        }}

        .comment-textarea::placeholder {{
            color: var(--text-muted);
        }}

        .form-actions {{
            display: flex;
            gap: 8px;
            margin-top: 12px;
        }}

        /* Comment list */
        .comment-list {{
            display: none;
        }}

        .comment-list.active {{
            display: block;
        }}

        .comment-item {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 10px;
            cursor: pointer;
            transition: border-color 0.15s;
        }}

        .comment-item:hover {{
            border-color: var(--accent);
        }}

        .comment-item-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }}

        .comment-item-label {{
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--accent);
        }}

        .comment-item-delete {{
            background: none;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            font-size: 1rem;
            padding: 0 4px;
        }}

        .comment-item-delete:hover {{
            color: var(--danger);
        }}

        .comment-item-text {{
            font-size: 0.8rem;
            color: var(--text-secondary);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-bottom: 4px;
        }}

        .comment-item-instruction {{
            font-size: 0.85rem;
            color: var(--text-primary);
        }}

        .empty-state {{
            text-align: center;
            padding: 40px 20px;
            color: var(--text-muted);
            font-size: 0.875rem;
            line-height: 1.8;
        }}

        /* Buttons */
        button {{
            padding: 0.5rem 1rem;
            border: none;
            border-radius: 6px;
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s;
        }}

        .btn-primary {{
            background: var(--accent);
            color: white;
        }}
        .btn-primary:hover {{
            background: var(--accent-hover);
        }}
        .btn-primary:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}

        .btn-secondary {{
            background: var(--bg-tertiary);
            color: var(--text-primary);
            border: 1px solid var(--border);
        }}
        .btn-secondary:hover {{
            background: var(--border);
        }}

        .btn-success {{
            background: var(--success);
            color: white;
        }}
        .btn-success:hover {{
            opacity: 0.9;
        }}

        .btn-danger {{
            background: transparent;
            color: var(--danger);
            border: 1px solid var(--danger);
        }}
        .btn-danger:hover {{
            background: var(--danger);
            color: white;
        }}

        .btn-sm {{
            padding: 0.3rem 0.6rem;
            font-size: 0.75rem;
        }}

        /* Bottom action bar */
        .action-bar {{
            padding: 16px 20px;
            border-top: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .keyboard-hint {{
            font-size: 0.75rem;
            color: var(--text-muted);
        }}

        kbd {{
            background: var(--bg-tertiary);
            padding: 0.15rem 0.35rem;
            border-radius: 3px;
            font-family: inherit;
            border: 1px solid var(--border);
            font-size: 0.7rem;
        }}

        /* Tabs */
        .tabs {{
            display: flex;
            border-bottom: 1px solid var(--border);
        }}

        .tab {{
            flex: 1;
            padding: 10px;
            text-align: center;
            font-size: 0.85rem;
            font-weight: 500;
            color: var(--text-muted);
            cursor: pointer;
            border-bottom: 2px solid transparent;
            background: none;
            border-radius: 0;
        }}

        .tab:hover {{
            color: var(--text-secondary);
        }}

        .tab.active {{
            color: var(--accent);
            border-bottom-color: var(--accent);
        }}

        @media (max-width: 900px) {{
            .layout {{
                flex-direction: column;
            }}
            .sidebar {{
                width: 100%;
                height: auto;
                position: static;
                border-left: none;
                border-top: 1px solid var(--border);
            }}
        }}
    </style>
</head>
<body>
    <div class="layout">
        <div class="main-content">
            <header>
                <h1>{title}</h1>
                <span class="badge" id="commentCountBadge">0 comments</span>
            </header>
            <p class="description">
                Click on any paragraph to add an editing instruction. When done, click Submit.
            </p>
            <div class="document-container" id="documentContainer"></div>

            <div class="action-bar" style="border-top: none; margin-top: 1rem; padding: 0;">
                <div class="keyboard-hint">
                    <kbd>Cmd</kbd>+<kbd>Enter</kbd> submit
                </div>
            </div>
        </div>

        <div class="sidebar">
            <div class="tabs">
                <div class="tab active" data-tab="edit" onclick="switchTab('edit')">Edit</div>
                <div class="tab" data-tab="comments" onclick="switchTab('comments')">Comments (<span id="commentTabCount">0</span>)</div>
            </div>

            <div class="sidebar-content">
                <!-- Edit tab: comment form -->
                <div class="comment-form" id="commentForm">
                    <label class="form-label">Selected paragraph</label>
                    <div class="selected-text-preview" id="selectedPreview"></div>

                    <label class="form-label">Editing instruction</label>
                    <textarea class="comment-textarea" id="commentInput"
                        placeholder="Enter your editing instruction...&#10;&#10;Examples:&#10;- Make this more concise&#10;- Change tone to formal&#10;- Add more detail about X"></textarea>

                    <div class="form-actions">
                        <button class="btn-primary" onclick="saveComment()">Save</button>
                        <button class="btn-secondary" onclick="cancelEdit()">Cancel</button>
                    </div>
                </div>

                <!-- Edit tab: empty state -->
                <div class="empty-state" id="editEmpty">
                    Click a paragraph on the left<br>to add an editing instruction.
                </div>

                <!-- Comments tab: list -->
                <div class="comment-list" id="commentList"></div>
                <div class="empty-state" id="commentsEmpty" style="display:none;">
                    No comments yet.
                </div>
            </div>

            <div class="action-bar">
                <button class="btn-secondary" onclick="cancelAll()">Cancel</button>
                <button class="btn-success" id="submitBtn" onclick="submitComments()" disabled>Submit Comments</button>
            </div>
        </div>
    </div>

    <script>
        const rawContent = {content_json};
        const paragraphs = {paragraphs_json};
        const serverPort = {server_port};

        // State
        let selectedIndex = null;
        let commentMap = {{}};  // paragraph_index -> instruction text
        let currentTab = 'edit';

        // Initialize: render paragraphs
        function init() {{
            const container = document.getElementById('documentContainer');
            container.innerHTML = paragraphs.map(p => {{
                let html = '';
                if (p.block_type === 'code') {{
                    html = '<pre><code>' + escapeHtml(p.text) + '</code></pre>';
                }} else if (p.block_type === 'hr') {{
                    html = '<hr>';
                }} else {{
                    html = marked.parse(p.raw);
                }}
                return `<div class="paragraph-block" data-index="${{p.index}}" onclick="selectParagraph(${{p.index}})">
                    ${{html}}
                    <span class="paragraph-index">#${{p.index + 1}}</span>
                </div>`;
            }}).join('');
        }}

        function escapeHtml(text) {{
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}

        function selectParagraph(index) {{
            // Deselect previous
            document.querySelectorAll('.paragraph-block.selected').forEach(el => el.classList.remove('selected'));

            // Select new
            const block = document.querySelector(`.paragraph-block[data-index="${{index}}"]`);
            if (block) block.classList.add('selected');

            selectedIndex = index;
            const p = paragraphs[index];

            // Show form
            document.getElementById('editEmpty').style.display = 'none';
            document.getElementById('commentForm').classList.add('active');
            document.getElementById('selectedPreview').textContent = p.text.substring(0, 300) + (p.text.length > 300 ? '...' : '');

            // Load existing comment if any
            document.getElementById('commentInput').value = commentMap[index] || '';
            document.getElementById('commentInput').focus();

            // Switch to edit tab
            if (currentTab !== 'edit') switchTab('edit');
        }}

        function saveComment() {{
            if (selectedIndex === null) return;
            const text = document.getElementById('commentInput').value.trim();
            if (!text) return;

            commentMap[selectedIndex] = text;

            // Update paragraph visual
            const block = document.querySelector(`.paragraph-block[data-index="${{selectedIndex}}"]`);
            if (block) {{
                block.classList.add('has-comment');
                // Add/update badge
                let badge = block.querySelector('.comment-badge');
                if (!badge) {{
                    badge = document.createElement('span');
                    badge.className = 'comment-badge';
                    badge.textContent = '!';
                    block.appendChild(badge);
                }}
            }}

            updateCounts();
            cancelEdit();
            renderCommentList();
        }}

        function cancelEdit() {{
            selectedIndex = null;
            document.querySelectorAll('.paragraph-block.selected').forEach(el => el.classList.remove('selected'));
            document.getElementById('commentForm').classList.remove('active');
            document.getElementById('editEmpty').style.display = 'block';
        }}

        function deleteComment(index) {{
            delete commentMap[index];
            const block = document.querySelector(`.paragraph-block[data-index="${{index}}"]`);
            if (block) {{
                block.classList.remove('has-comment');
                const badge = block.querySelector('.comment-badge');
                if (badge) badge.remove();
            }}
            updateCounts();
            renderCommentList();
        }}

        function updateCounts() {{
            const count = Object.keys(commentMap).length;
            document.getElementById('commentCountBadge').textContent = count + ' comment' + (count !== 1 ? 's' : '');
            document.getElementById('commentTabCount').textContent = count;
            document.getElementById('submitBtn').disabled = count === 0;
        }}

        function renderCommentList() {{
            const list = document.getElementById('commentList');
            const empty = document.getElementById('commentsEmpty');
            const entries = Object.entries(commentMap).sort((a, b) => Number(a[0]) - Number(b[0]));

            if (entries.length === 0) {{
                list.innerHTML = '';
                if (currentTab === 'comments') empty.style.display = 'block';
                return;
            }}

            empty.style.display = 'none';
            list.innerHTML = entries.map(([idx, instruction]) => {{
                const p = paragraphs[Number(idx)];
                const preview = p.text.substring(0, 60) + (p.text.length > 60 ? '...' : '');
                return `<div class="comment-item" onclick="selectParagraph(${{idx}})">
                    <div class="comment-item-header">
                        <span class="comment-item-label">Paragraph #${{Number(idx) + 1}}</span>
                        <button class="comment-item-delete" onclick="event.stopPropagation(); deleteComment(${{idx}})">&times;</button>
                    </div>
                    <div class="comment-item-text">${{escapeHtml(preview)}}</div>
                    <div class="comment-item-instruction">${{escapeHtml(instruction)}}</div>
                </div>`;
            }}).join('');
        }}

        function switchTab(tab) {{
            currentTab = tab;
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelector(`.tab[data-tab="${{tab}}"]`).classList.add('active');

            if (tab === 'edit') {{
                document.getElementById('commentForm').classList.toggle('active', selectedIndex !== null);
                document.getElementById('editEmpty').style.display = selectedIndex !== null ? 'none' : 'block';
                document.getElementById('commentList').classList.remove('active');
                document.getElementById('commentsEmpty').style.display = 'none';
            }} else {{
                document.getElementById('commentForm').classList.remove('active');
                document.getElementById('editEmpty').style.display = 'none';
                document.getElementById('commentList').classList.add('active');
                renderCommentList();
                if (Object.keys(commentMap).length === 0) {{
                    document.getElementById('commentsEmpty').style.display = 'block';
                }}
            }}
        }}

        async function submitComments() {{
            const comments = Object.entries(commentMap).map(([idx, instruction]) => {{
                const p = paragraphs[Number(idx)];
                return {{
                    paragraph_index: Number(idx),
                    paragraph_text: p.raw,
                    instruction: instruction
                }};
            }}).sort((a, b) => a.paragraph_index - b.paragraph_index);

            const result = {{
                status: 'submitted',
                comments: comments
            }};

            try {{
                await fetch(`http://localhost:${{serverPort}}/submit`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(result)
                }});
                window.close();
            }} catch (e) {{
                console.error('Submit failed:', e);
            }}
        }}

        async function cancelAll() {{
            try {{
                await fetch(`http://localhost:${{serverPort}}/submit`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ status: 'cancelled', comments: [] }})
                }});
                window.close();
            }} catch (e) {{
                window.close();
            }}
        }}

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {{
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {{
                e.preventDefault();
                if (!document.getElementById('submitBtn').disabled) {{
                    submitComments();
                }}
            }}
            if (e.key === 'Escape') {{
                if (selectedIndex !== null) {{
                    cancelEdit();
                }}
            }}
        }});

        // Cmd+Enter in textarea also submits the comment (saves first)
        document.getElementById('commentInput').addEventListener('keydown', (e) => {{
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {{
                e.preventDefault();
                if (document.getElementById('commentInput').value.trim()) {{
                    saveComment();
                }}
                if (!document.getElementById('submitBtn').disabled) {{
                    submitComments();
                }}
            }}
        }});

        init();
    </script>
</body>
</html>'''


def generate_review_html(title: str, changes: list[dict], server_port: int) -> str:
    """
    Generate HTML for Phase 2: Review Changes UI.

    Shows original vs suggested text as diffs.
    Users can Accept/Reject each change individually or all at once.
    """
    changes_json = json.dumps(changes, ensure_ascii=False)

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Review Changes</title>
    <style>
        :root {{
            --bg-primary: #0d1117;
            --bg-secondary: #161b22;
            --bg-tertiary: #21262d;
            --bg-card: #1c2128;
            --text-primary: #e6edf3;
            --text-secondary: #8b949e;
            --text-muted: #6e7681;
            --accent: #58a6ff;
            --accent-hover: #79b8ff;
            --success: #3fb950;
            --success-bg: rgba(63, 185, 80, 0.15);
            --danger: #f85149;
            --danger-bg: rgba(248, 81, 73, 0.15);
            --warning: #d29922;
            --border: #30363d;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            min-height: 100vh;
            padding: 2rem;
        }}

        .container {{
            max-width: 900px;
            margin: 0 auto;
        }}

        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--border);
        }}

        header h1 {{
            font-size: 1.5rem;
            font-weight: 600;
        }}

        .summary-badges {{
            display: flex;
            gap: 8px;
        }}

        .badge {{
            padding: 0.25rem 0.75rem;
            border-radius: 12px;
            font-size: 0.8rem;
        }}

        .badge-pending {{
            background: var(--bg-tertiary);
            color: var(--text-secondary);
        }}

        .badge-accepted {{
            background: var(--success-bg);
            color: var(--success);
        }}

        .badge-rejected {{
            background: var(--danger-bg);
            color: var(--danger);
        }}

        .bulk-actions {{
            display: flex;
            gap: 8px;
            margin-bottom: 1.5rem;
        }}

        /* Change card */
        .change-card {{
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 8px;
            margin-bottom: 1rem;
            overflow: hidden;
            transition: border-color 0.15s;
        }}

        .change-card.accepted {{
            border-color: var(--success);
        }}

        .change-card.rejected {{
            border-color: var(--danger);
        }}

        .change-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 16px;
            background: var(--bg-tertiary);
            border-bottom: 1px solid var(--border);
        }}

        .change-label {{
            font-size: 0.85rem;
            font-weight: 600;
        }}

        .change-instruction {{
            font-size: 0.8rem;
            color: var(--text-secondary);
            padding: 8px 16px;
            border-bottom: 1px solid var(--border);
            font-style: italic;
        }}

        .change-status {{
            font-size: 0.75rem;
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 600;
        }}

        .status-pending {{
            background: var(--bg-primary);
            color: var(--text-muted);
        }}

        .status-accepted {{
            background: var(--success-bg);
            color: var(--success);
        }}

        .status-rejected {{
            background: var(--danger-bg);
            color: var(--danger);
        }}

        .diff-container {{
            padding: 16px;
        }}

        .diff-section {{
            margin-bottom: 12px;
        }}

        .diff-section:last-child {{
            margin-bottom: 0;
        }}

        .diff-label {{
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            margin-bottom: 4px;
            display: block;
        }}

        .diff-label.original {{
            color: var(--danger);
        }}

        .diff-label.suggested {{
            color: var(--success);
        }}

        .diff-text {{
            padding: 10px 14px;
            border-radius: 6px;
            font-size: 0.875rem;
            line-height: 1.6;
            white-space: pre-wrap;
            word-wrap: break-word;
        }}

        .diff-text.original {{
            background: var(--danger-bg);
            border-left: 3px solid var(--danger);
        }}

        .diff-text.suggested {{
            background: var(--success-bg);
            border-left: 3px solid var(--success);
        }}

        .change-actions {{
            display: flex;
            gap: 8px;
            padding: 12px 16px;
            border-top: 1px solid var(--border);
            justify-content: flex-end;
        }}

        /* Buttons */
        button {{
            padding: 0.5rem 1rem;
            border: none;
            border-radius: 6px;
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s;
        }}

        .btn-primary {{
            background: var(--accent);
            color: white;
        }}
        .btn-primary:hover {{
            background: var(--accent-hover);
        }}
        .btn-primary:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}

        .btn-secondary {{
            background: var(--bg-tertiary);
            color: var(--text-primary);
            border: 1px solid var(--border);
        }}
        .btn-secondary:hover {{
            background: var(--border);
        }}

        .btn-success {{
            background: var(--success);
            color: white;
        }}
        .btn-success:hover {{
            opacity: 0.9;
        }}

        .btn-danger {{
            background: transparent;
            color: var(--danger);
            border: 1px solid var(--danger);
        }}
        .btn-danger:hover {{
            background: var(--danger);
            color: white;
        }}

        .btn-sm {{
            padding: 0.3rem 0.6rem;
            font-size: 0.75rem;
        }}

        .btn-outline-success {{
            background: transparent;
            color: var(--success);
            border: 1px solid var(--success);
        }}
        .btn-outline-success:hover {{
            background: var(--success);
            color: white;
        }}

        .btn-outline-danger {{
            background: transparent;
            color: var(--danger);
            border: 1px solid var(--danger);
        }}
        .btn-outline-danger:hover {{
            background: var(--danger);
            color: white;
        }}

        /* Bottom bar */
        .bottom-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 1.5rem;
            padding-top: 1rem;
            border-top: 1px solid var(--border);
        }}

        .keyboard-hint {{
            font-size: 0.75rem;
            color: var(--text-muted);
        }}

        kbd {{
            background: var(--bg-tertiary);
            padding: 0.15rem 0.35rem;
            border-radius: 3px;
            font-family: inherit;
            border: 1px solid var(--border);
            font-size: 0.7rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{title}</h1>
            <div class="summary-badges">
                <span class="badge badge-pending" id="pendingBadge">0 pending</span>
                <span class="badge badge-accepted" id="acceptedBadge">0 accepted</span>
                <span class="badge badge-rejected" id="rejectedBadge">0 rejected</span>
            </div>
        </header>

        <div class="bulk-actions">
            <button class="btn-outline-success btn-sm" onclick="acceptAll()">Accept All</button>
            <button class="btn-outline-danger btn-sm" onclick="rejectAll()">Reject All</button>
            <button class="btn-secondary btn-sm" onclick="resetAll()">Reset All</button>
        </div>

        <div id="changesList"></div>

        <div class="bottom-bar">
            <div class="keyboard-hint">
                <kbd>Cmd</kbd>+<kbd>Enter</kbd> submit
            </div>
            <div style="display:flex; gap:8px;">
                <button class="btn-secondary" onclick="cancelReview()">Cancel</button>
                <button class="btn-primary" id="submitBtn" onclick="submitReview()">Submit Decisions</button>
            </div>
        </div>
    </div>

    <script>
        const changes = {changes_json};
        const serverPort = {server_port};

        // State: 'pending' | 'accepted' | 'rejected'
        let decisions = changes.map(() => 'pending');

        function escapeHtml(text) {{
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}

        function renderChanges() {{
            const container = document.getElementById('changesList');
            container.innerHTML = changes.map((change, i) => {{
                const status = decisions[i];
                return `<div class="change-card ${{status}}" id="card-${{i}}">
                    <div class="change-header">
                        <span class="change-label">Paragraph #${{change.paragraph_index + 1}}</span>
                        <span class="change-status status-${{status}}">${{status.toUpperCase()}}</span>
                    </div>
                    <div class="change-instruction">${{escapeHtml(change.instruction)}}</div>
                    <div class="diff-container">
                        <div class="diff-section">
                            <span class="diff-label original">Original</span>
                            <div class="diff-text original">${{escapeHtml(change.original)}}</div>
                        </div>
                        <div class="diff-section">
                            <span class="diff-label suggested">Suggested</span>
                            <div class="diff-text suggested">${{escapeHtml(change.suggested)}}</div>
                        </div>
                    </div>
                    <div class="change-actions">
                        <button class="btn-sm ${{status === 'accepted' ? 'btn-success' : 'btn-outline-success'}}"
                                onclick="setDecision(${{i}}, 'accepted')">Accept</button>
                        <button class="btn-sm ${{status === 'rejected' ? 'btn-danger' : 'btn-outline-danger'}}"
                                onclick="setDecision(${{i}}, 'rejected')">Reject</button>
                    </div>
                </div>`;
            }}).join('');

            updateBadges();
        }}

        function setDecision(index, status) {{
            decisions[index] = decisions[index] === status ? 'pending' : status;
            renderChanges();
        }}

        function acceptAll() {{
            decisions = decisions.map(() => 'accepted');
            renderChanges();
        }}

        function rejectAll() {{
            decisions = decisions.map(() => 'rejected');
            renderChanges();
        }}

        function resetAll() {{
            decisions = decisions.map(() => 'pending');
            renderChanges();
        }}

        function updateBadges() {{
            const pending = decisions.filter(d => d === 'pending').length;
            const accepted = decisions.filter(d => d === 'accepted').length;
            const rejected = decisions.filter(d => d === 'rejected').length;

            document.getElementById('pendingBadge').textContent = `${{pending}} pending`;
            document.getElementById('acceptedBadge').textContent = `${{accepted}} accepted`;
            document.getElementById('rejectedBadge').textContent = `${{rejected}} rejected`;
        }}

        async function submitReview() {{
            const result = {{
                status: 'submitted',
                decisions: changes.map((change, i) => ({{
                    paragraph_index: change.paragraph_index,
                    original: change.original,
                    suggested: change.suggested,
                    accepted: decisions[i] === 'accepted'
                }}))
            }};

            try {{
                await fetch(`http://localhost:${{serverPort}}/submit`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(result)
                }});
                window.close();
            }} catch (e) {{
                console.error('Submit failed:', e);
            }}
        }}

        async function cancelReview() {{
            try {{
                await fetch(`http://localhost:${{serverPort}}/submit`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ status: 'cancelled', decisions: [] }})
                }});
                window.close();
            }} catch (e) {{
                window.close();
            }}
        }}

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {{
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {{
                e.preventDefault();
                submitReview();
            }}
            if (e.key === 'Escape') {{
                cancelReview();
            }}
        }});

        renderChanges();
    </script>
</body>
</html>'''
