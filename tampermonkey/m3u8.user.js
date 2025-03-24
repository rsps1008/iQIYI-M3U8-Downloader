// ==UserScript==
// @name         M3U8提取
// @namespace    http://tampermonkey.net/
// @description  Get M3U8 list from iq
// @version      1.0.0
// @match        *://www.iq.com/play/*
// @author       rsps1008
// @run-at       document-start
// @grant        GM_xmlhttpRequest
// ==/UserScript==

(function() {
  'use strict';

  /**
   * 每隔3秒掃描 <script>，若發現 "m3u8" 就嘗試擷取
   */
  function pollScriptTags() {
    const intervalId = setInterval(() => {
      console.log('[DEBUG] 週期檢查 <script>，尋找 "m3u8"');
      if (checkScriptTags()) {
        console.log('[DEBUG] 已找到 m3u8Content，停止輪詢');
        clearInterval(intervalId);
      }
    }, 3000);
  }

  /**
   * 在所有 <script> 中搜尋含 'm3u8' 的字串
   * 並用正則 /"m3u8":\s*"([^"]+)"/ 擷取 m3u8Content
   */
    function checkScriptTags() {
        let found = false;
        const scripts = document.querySelectorAll('script');

        for (const sc of scripts) {
            if (sc.innerText.includes('m3u8') || sc.innerText.includes('.srt')) {
                console.log('[DEBUG] 發現含 m3u8 或 srt 的 <script>');
                found = true;

                // 擷取 "m3u8": "..." 或 ".srt" URL
                const m3u8Match = sc.innerText.match(/"m3u8":\s*"([^"]+)"/);
                const srtMatch = sc.innerText.match(/"srt":\s*"([^"]+)"/);

                const rawM3U8 = m3u8Match ? m3u8Match[1] : null;
                const rawSRT = srtMatch ? srtMatch[1] : null;

                if (rawM3U8 || rawSRT) {
                    console.log('[DEBUG] 取得 m3u8 (前100字):', rawM3U8 ? rawM3U8.slice(0, 100) : '無', '...');
                    console.log('[DEBUG] 取得 srt (前100字):', rawSRT ? rawSRT.slice(0, 100) : '無', '...');
                    sendToPython(rawM3U8, rawSRT);
                } else {
                    console.warn('[WARN] 含 m3u8 或 srt，但無法 match 到完整字串');
                }
            }
        }
        return found;
    }


  /**
   * 將擷取到的 m3u8Content 傳給本地 Python (port=18888)
   */
    function sendToPython(m3u8Str, srtStr) {
        const videoElement = document.querySelector('video');
        const payload = {
            fileName: document.title || 'Video',
            m3u8Content: m3u8Str || '',
            srtContent: srtStr || '',
            duration: videoElement.duration || '',
        };

        GM_xmlhttpRequest({
            method: 'POST',
            url: 'http://127.0.0.1:18888',
            data: JSON.stringify(payload),
            headers: {
                'Content-Type': 'application/json'
            },
            onload: function(res) {
                console.log('[DEBUG] 伺服器回應:', res.response);
                if (res.response === 'success') {
                    console.log('[INFO] 成功送出 m3u8Content 和 srtContent -> Python');
                } else {
                    console.error('[ERROR] Python 回應失敗:', res.response);
                }
            },
            onerror: function(err) {
                console.error('[ERROR] 無法連線 127.0.0.1:18888:', err);
            }
        });
    }

  /**
   * DOM 載入後，在 class="intl-play-main-title " 中加入 <a> 下載影片</a>
   * 只有點擊時才開始 pollScriptTags()
   */
  window.addEventListener('DOMContentLoaded', () => {
    console.log('[INFO] DOM 已加載，準備建立「下載影片」連結');
    setTimeout(() => {
        // 尋找目標 <div class="intl-play-main-title ">
        const mainTitleDiv = document.querySelector('.intl-play-main-title');
        if (mainTitleDiv) {
            // 建立 <a> 元素
            const downloadLink = document.createElement('a');
            downloadLink.textContent = '下載影片';
            downloadLink.href = 'javascript:void(0)';
            downloadLink.style.cssText = 'margin-left:10px; cursor:pointer; color:red; text-decoration:underline;';
            downloadLink.addEventListener('click', () => {
                console.log('[DEBUG] 使用者點擊「下載影片」，開始週期偵測 M3U8');
                pollScriptTags();
            });

            // 插入到 div 裏面
            mainTitleDiv.appendChild(downloadLink);
            console.log('[INFO]「下載影片」建立成功');
        } else {
            console.warn('[WARN] 未找到 class="intl-play-main-title " 的元素，無法插入「下載影片」連結');
        }
    }, 5000);
    console.log('[INFO] Userscript (點擊後偵測 m3u8) 已載入');
  });

})();
