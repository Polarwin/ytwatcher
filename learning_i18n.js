'use strict';
(() => {
  const messages = {
  "Interface language": {
    "es": "Idioma de la interfaz",
    "de": "Sprache der Oberfläche",
    "zh": "界面语言"
  },
  "← Learning clips": {
    "es": "← Clips de aprendizaje",
    "de": "← Lernclips",
    "zh": "← 学习片段"
  },
  "Learning clips": {
    "es": "Clips de aprendizaje",
    "de": "Lernclips",
    "zh": "学习片段"
  },
  "Learning clip": {
    "es": "Clip de aprendizaje",
    "de": "Lernclip",
    "zh": "学习片段"
  },
  "Save offline": {
    "es": "Guardar sin conexión",
    "de": "Offline speichern",
    "zh": "保存供离线使用"
  },
  "Remove offline copy": {
    "es": "Eliminar copia sin conexión",
    "de": "Offline-Kopie entfernen",
    "zh": "删除离线副本"
  },
  "Save this clip on this device before going offline.": {
    "es": "Guarda este clip en el dispositivo antes de desconectarte.",
    "de": "Speichere diesen Clip vor dem Trennen auf diesem Gerät.",
    "zh": "请先将片段保存在此设备，再断开网络。"
  },
  "Learning activities": {
    "es": "Actividades de aprendizaje",
    "de": "Lernaktivitäten",
    "zh": "学习活动"
  },
  "Listen & speak": {
    "es": "Escuchar y hablar",
    "de": "Hören und sprechen",
    "zh": "听说练习"
  },
  "Reading": {
    "es": "Lectura",
    "de": "Lesen",
    "zh": "阅读"
  },
  "Vocabulary": {
    "es": "Vocabulario",
    "de": "Wortschatz",
    "zh": "词汇"
  },
  "Landscape": {
    "es": "Horizontal",
    "de": "Querformat",
    "zh": "横屏"
  },
  "Exit landscape": {
    "es": "Salir del modo horizontal",
    "de": "Querformat beenden",
    "zh": "退出横屏"
  },
  "Close word lookup": {
    "es": "Cerrar consulta de palabra",
    "de": "Wortsuche schließen",
    "zh": "关闭查词"
  },
  "← Previous": {
    "es": "← Anterior",
    "de": "← Zurück",
    "zh": "← 上一句"
  },
  "Play / repeat": {
    "es": "Reproducir / repetir",
    "de": "Abspielen / wiederholen",
    "zh": "播放 / 重复"
  },
  "Next →": {
    "es": "Siguiente →",
    "de": "Weiter →",
    "zh": "下一句 →"
  },
  "Continue ▶": {
    "es": "Continuar ▶",
    "de": "Fortsetzen ▶",
    "zh": "继续 ▶"
  },
  "Pause each sentence": {
    "es": "Pausar tras cada frase",
    "de": "Nach jedem Satz pausieren",
    "zh": "每句结束后暂停"
  },
  "Loop sentence": {
    "es": "Repetir frase en bucle",
    "de": "Satz in Schleife abspielen",
    "zh": "循环播放本句"
  },
  "Speed": {
    "es": "Velocidad",
    "de": "Geschwindigkeit",
    "zh": "速度"
  },
  "Copy sentence": {
    "es": "Copiar frase",
    "de": "Satz kopieren",
    "zh": "复制句子"
  },
  "Translate sentence": {
    "es": "Traducir frase",
    "de": "Satz übersetzen",
    "zh": "翻译句子"
  },
  "Translation": {
    "es": "Traducción",
    "de": "Übersetzung",
    "zh": "翻译"
  },
  "Mark reviewed": {
    "es": "Marcar como repasada",
    "de": "Als wiederholt markieren",
    "zh": "标记为已复习"
  },
  "✓ Reviewed": {
    "es": "✓ Repasada",
    "de": "✓ Wiederholt",
    "zh": "✓ 已复习"
  },
  "● Record my voice": {
    "es": "● Grabar mi voz",
    "de": "● Meine Stimme aufnehmen",
    "zh": "● 录制我的声音"
  },
  "■ Stop & save": {
    "es": "■ Detener y guardar",
    "de": "■ Stoppen und speichern",
    "zh": "■ 停止并保存"
  },
  "Compare original → my voice": {
    "es": "Comparar original → mi voz",
    "de": "Original → meine Stimme vergleichen",
    "zh": "对比原音 → 我的录音"
  },
  "Listen, repeat aloud, then record yourself.": {
    "es": "Escucha, repite en voz alta y después grábate.",
    "de": "Höre zu, sprich laut nach und nimm dich dann auf.",
    "zh": "先听原音，跟读，再录下自己的声音。"
  },
  "My attempts": {
    "es": "Mis intentos",
    "de": "Meine Versuche",
    "zh": "我的录音"
  },
  "Voice recording attempts": {
    "es": "Intentos de grabación",
    "de": "Aufnahmeversuche",
    "zh": "录音记录"
  },
  "No recording yet": {
    "es": "Aún no hay grabaciones",
    "de": "Noch keine Aufnahme",
    "zh": "暂无录音"
  },
  "Download recording": {
    "es": "Descargar grabación",
    "de": "Aufnahme herunterladen",
    "zh": "下载录音"
  },
  "Delete this attempt": {
    "es": "Eliminar este intento",
    "de": "Diesen Versuch löschen",
    "zh": "删除这次录音"
  },
  "Recordings stay in this browser on this device. Download important attempts. Compare your recording with the original; no automatic pronunciation score is used.": {
    "es": "Las grabaciones se guardan en este navegador y dispositivo. Descarga los intentos importantes. Compara tu grabación con el original; no hay puntuación automática de pronunciación.",
    "de": "Aufnahmen bleiben in diesem Browser auf diesem Gerät. Lade wichtige Versuche herunter. Vergleiche deine Aufnahme mit dem Original; es gibt keine automatische Aussprachebewertung.",
    "zh": "录音仅保存在此设备的浏览器中。请下载重要的录音备份。通过对比原音和录音练习发音，不提供自动发音评分。"
  },
  "All sentences": {
    "es": "Todas las frases",
    "de": "Alle Sätze",
    "zh": "全部句子"
  },
  "Original subtitle text. Tap a word for its offline dictionary meaning, or use Listen to practise a sentence.": {
    "es": "Texto original de los subtítulos. Toca una palabra para consultar el diccionario sin conexión o pulsa Escuchar para practicar una frase.",
    "de": "Originaler Untertiteltext. Tippe auf ein Wort für die Offline-Bedeutung oder auf Anhören, um einen Satz zu üben.",
    "zh": "保留原文字幕。点击单词查看离线词义，或点击“听一句”练习句子。"
  },
  "Reading practice": {
    "es": "Práctica de lectura",
    "de": "Leseübungen",
    "zh": "阅读练习"
  },
  "Complete the sentences": {
    "es": "Completa las frases",
    "de": "Sätze vervollständigen",
    "zh": "补全句子"
  },
  "Use the vocabulary to fill each gap.": {
    "es": "Usa el vocabulario para completar cada hueco.",
    "de": "Fülle jede Lücke mit dem passenden Wort.",
    "zh": "使用词汇填入空白处。"
  },
  "Reading translation": {
    "es": "Traducción de la lectura",
    "de": "Übersetzung des Lesetexts",
    "zh": "阅读译文"
  },
  "Included learning material was generated by the local model from the subtitles. Suggested answers are for review.": {
    "es": "El material de aprendizaje incluido fue generado por el modelo local a partir de los subtítulos. Las respuestas sugeridas sirven para repasar.",
    "de": "Das enthaltene Lernmaterial wurde vom lokalen Modell aus den Untertiteln erstellt. Die Antwortvorschläge dienen der Wiederholung.",
    "zh": "附带的学习材料由本地模型根据字幕生成，参考答案供复习使用。"
  },
  "These dictionary entries travel with the clip. Your lookups are saved to your ytwatcher flashcards when connected.": {
    "es": "Estas entradas del diccionario se incluyen con el clip. Tus consultas se guardan en las tarjetas de ytwatcher cuando hay conexión.",
    "de": "Diese Wörterbucheinträge gehören zum Clip. Deine Abfragen werden bei bestehender Verbindung in deinen ytwatcher-Lernkarten gespeichert.",
    "zh": "这些词典条目随片段一起保存。联网时，查词记录会同步到你的 ytwatcher 闪卡。"
  },
  "Find a word": {
    "es": "Buscar una palabra",
    "de": "Wort suchen",
    "zh": "查找单词"
  },
  "Search vocabulary": {
    "es": "Buscar vocabulario",
    "de": "Wortschatz durchsuchen",
    "zh": "搜索词汇"
  },
  "Word": {
    "es": "Palabra",
    "de": "Wort",
    "zh": "单词"
  },
  "Meaning": {
    "es": "Significado",
    "de": "Bedeutung",
    "zh": "词义"
  },
  "Notes / word form": {
    "es": "Notas / forma de la palabra",
    "de": "Hinweise / Wortform",
    "zh": "说明 / 词形"
  },
  "Vocabulary quiz": {
    "es": "Prueba de vocabulario",
    "de": "Wortschatzquiz",
    "zh": "词汇测验"
  },
  "Random question": {
    "es": "Pregunta aleatoria",
    "de": "Zufällige Frage",
    "zh": "随机出题"
  },
  "Close vocabulary": {
    "es": "Cerrar vocabulario",
    "de": "Wortschatz schließen",
    "zh": "关闭词汇"
  },
  "Saved with your looked-up vocabulary. Other meanings may fit other contexts.": {
    "es": "Se guarda con tu vocabulario consultado. Otros significados pueden encajar en otros contextos.",
    "de": "Wird mit deinem nachgeschlagenen Wortschatz gespeichert. In anderen Zusammenhängen können andere Bedeutungen passen.",
    "zh": "保存到查词记录中。其他语境可能需要不同的词义。"
  },
  "Copy this sentence": {
    "es": "Copiar esta frase",
    "de": "Diesen Satz kopieren",
    "zh": "复制这句话"
  },
  "Sentence to copy": {
    "es": "Frase para copiar",
    "de": "Zu kopierender Satz",
    "zh": "待复制的句子"
  },
  "Close": {
    "es": "Cerrar",
    "de": "Schließen",
    "zh": "关闭"
  },
  "Export learning page": {
    "es": "Exportar página de aprendizaje",
    "de": "Lernseite exportieren",
    "zh": "导出学习页面"
  },
  "Close export": {
    "es": "Cerrar exportación",
    "de": "Export schließen",
    "zh": "关闭导出"
  },
  "Choose a short clip. The export includes complete sentences touching this range.": {
    "es": "Elige un clip corto. La exportación incluye las frases completas que coincidan con este intervalo.",
    "de": "Wähle einen kurzen Clip. Der Export enthält vollständige Sätze, die diesen Bereich berühren.",
    "zh": "请选择一个短片段，导出时会包含与此时间范围相交的完整句子。"
  },
  "Start (minutes:seconds)": {
    "es": "Inicio (minutos:segundos)",
    "de": "Start (Minuten:Sekunden)",
    "zh": "开始（分:秒）"
  },
  "End": {
    "es": "Fin",
    "de": "Ende",
    "zh": "结束"
  },
  "Whole video": {
    "es": "Vídeo completo",
    "de": "Ganzes Video",
    "zh": "整个视频"
  },
  "Subtitles": {
    "es": "Subtítulos",
    "de": "Untertitel",
    "zh": "字幕"
  },
  "Generate reading translations and comprehension questions with the local LLM": {
    "es": "Generar traducciones de lectura y preguntas de comprensión con el modelo local",
    "de": "Leseübersetzungen und Verständnisfragen mit dem lokalen Sprachmodell erstellen",
    "zh": "使用本地大模型生成阅读译文和理解题"
  },
  "Optional; best for clips of about 3–5 minutes. Uses the gateway’s default model.": {
    "es": "Opcional; mejor para clips de unos 3–5 minutos. Usa el modelo predeterminado de la pasarela.",
    "de": "Optional; am besten für Clips von etwa 3–5 Minuten. Verwendet das Standardmodell des Gateways.",
    "zh": "可选，建议使用约 3–5 分钟的片段。使用网关的默认模型。"
  },
  "Includes sentence pauses, repeat, original subtitles, word lookup, reading, vocabulary quiz, and recording your own voice. Choose": {
    "es": "Incluye pausas por frase, repetición, subtítulos originales, consulta de palabras, lectura, prueba de vocabulario y grabación de voz. Elige",
    "de": "Enthält Satzpausen, Wiederholung, Originaluntertitel, Wortsuche, Lesen, Wortschatzquiz und eigene Aufnahmen. Wähle",
    "zh": "包含逐句暂停、重复播放、原文字幕、查词、阅读、词汇测验和录音。请在完成的页面点击"
  },
  "on the finished page before disconnecting.": {
    "es": "en la página terminada antes de desconectarte.",
    "de": "auf der fertigen Seite, bevor du die Verbindung trennst.",
    "zh": "，然后再断开网络。"
  },
  "Create learning page": {
    "es": "Crear página de aprendizaje",
    "de": "Lernseite erstellen",
    "zh": "创建学习页面"
  },
  "Open learning page": {
    "es": "Abrir página de aprendizaje",
    "de": "Lernseite öffnen",
    "zh": "打开学习页面"
  },
  "All exported learning clips": {
    "es": "Todos los clips de aprendizaje exportados",
    "de": "Alle exportierten Lernclips",
    "zh": "所有已导出的学习片段"
  },
  "Learn": {
    "es": "Aprender",
    "de": "Lernen",
    "zh": "学习"
  },
  "Download subtitles for this video first.": {
    "es": "Descarga primero los subtítulos de este vídeo.",
    "de": "Lade zuerst die Untertitel dieses Videos herunter.",
    "zh": "请先下载此视频的字幕。"
  },
  "Choose a valid start and end, up to 2 hours apart.": {
    "es": "Elige un inicio y un fin válidos, con una duración máxima de 2 horas.",
    "de": "Wähle einen gültigen Start und ein gültiges Ende mit höchstens 2 Stunden Abstand.",
    "zh": "请选择有效的开始和结束时间，最长为 2 小时。"
  },
  "Starting export…": {
    "es": "Iniciando exportación…",
    "de": "Export wird gestartet…",
    "zh": "正在开始导出…"
  },
  "Could not start export": {
    "es": "No se pudo iniciar la exportación",
    "de": "Export konnte nicht gestartet werden",
    "zh": "无法开始导出"
  },
  "Export status unavailable": {
    "es": "Estado de exportación no disponible",
    "de": "Exportstatus nicht verfügbar",
    "zh": "无法获取导出状态"
  },
  "Status will retry when connected.": {
    "es": "Se volverá a consultar el estado al conectar.",
    "de": "Der Status wird bei Verbindung erneut abgefragt.",
    "zh": "恢复连接后会重试获取状态。"
  },
  "{n} sentences": {
    "es": "{n} frases",
    "de": "{n} Sätze",
    "zh": "{n} 句"
  },
  "Share this lesson through Frankfurt. Anyone with the link can open it until expiry. Offline/downloaded copies remain available.": {
    "es": "Comparte esta lección a través de Frankfurt. Cualquier persona con el enlace puede abrirla hasta que caduque. Las copias guardadas sin conexión siguen disponibles.",
    "de": "Teile diese Lektion über Frankfurt. Jeder mit dem Link kann sie bis zum Ablauf öffnen. Offline gespeicherte Kopien bleiben verfügbar.",
    "zh": "通过法兰克福分享此课程。任何持有链接的人都可在到期前打开，已保存的离线副本仍可继续使用。"
  },
  "Share link lifetime": {
    "es": "Duración del enlace compartido",
    "de": "Gültigkeit des Freigabelinks",
    "zh": "分享链接有效期"
  },
  "5 days": {
    "es": "5 días",
    "de": "5 Tage",
    "zh": "5 天"
  },
  "1 day": {
    "es": "1 día",
    "de": "1 Tag",
    "zh": "1 天"
  },
  "Create temporary link": {
    "es": "Crear enlace temporal",
    "de": "Temporären Link erstellen",
    "zh": "创建临时链接"
  },
  "Open shared lesson": {
    "es": "Abrir lección compartida",
    "de": "Geteilte Lektion öffnen",
    "zh": "打开分享的课程"
  },
  "Temporary lesson link": {
    "es": "Enlace temporal de la lección",
    "de": "Temporärer Lektionslink",
    "zh": "课程临时链接"
  },
  "Copy link": {
    "es": "Copiar enlace",
    "de": "Link kopieren",
    "zh": "复制链接"
  },
  "Revoke link": {
    "es": "Revocar enlace",
    "de": "Link widerrufen",
    "zh": "撤销链接"
  },
  "Link expires {date}": {
    "es": "El enlace caduca el {date}",
    "de": "Link läuft am {date} ab",
    "zh": "链接将于 {date} 到期"
  },
  "Link expired. Create a new link.": {
    "es": "El enlace ha caducado. Crea uno nuevo.",
    "de": "Link abgelaufen. Erstelle einen neuen Link.",
    "zh": "链接已到期，请创建新链接。"
  },
  "Link revoked.": {
    "es": "Enlace revocado.",
    "de": "Link widerrufen.",
    "zh": "链接已撤销。"
  },
  "Share status unavailable": {
    "es": "Estado del enlace no disponible",
    "de": "Freigabestatus nicht verfügbar",
    "zh": "无法获取分享状态"
  },
  "Revoking…": {
    "es": "Revocando…",
    "de": "Wird widerrufen…",
    "zh": "正在撤销…"
  },
  "Uploading lesson…": {
    "es": "Subiendo lección…",
    "de": "Lektion wird hochgeladen…",
    "zh": "正在上传课程…"
  },
  "Sharing unavailable": {
    "es": "No se puede compartir ahora",
    "de": "Teilen derzeit nicht verfügbar",
    "zh": "暂时无法分享"
  },
  "Link copied. Expires {date}": {
    "es": "Enlace copiado. Caduca el {date}",
    "de": "Link kopiert. Gültig bis {date}",
    "zh": "链接已复制，将于 {date} 到期"
  },
  "Link selected. Use Copy from the browser menu.": {
    "es": "Enlace seleccionado. Usa Copiar en el menú del navegador.",
    "de": "Link ausgewählt. Wähle Kopieren im Browsermenü.",
    "zh": "链接已选中，请使用浏览器菜单中的“复制”。"
  },
  "Copying lesson to Frankfurt": {
    "es": "Copiando lección a Frankfurt",
    "de": "Lektion wird nach Frankfurt kopiert",
    "zh": "正在将课程复制到法兰克福"
  },
  "Revoking link": {
    "es": "Revocando enlace",
    "de": "Link wird widerrufen",
    "zh": "正在撤销链接"
  },
  "Ready to share": {
    "es": "Lista para compartir",
    "de": "Zum Teilen bereit",
    "zh": "可以分享了"
  },
  "Link revoked": {
    "es": "Enlace revocado",
    "de": "Link widerrufen",
    "zh": "链接已撤销"
  },
  "Waiting to export": {
    "es": "Esperando exportación",
    "de": "Warten auf Export",
    "zh": "等待导出"
  },
  "Reading subtitles and sentence boundaries": {
    "es": "Leyendo subtítulos y límites de frases",
    "de": "Untertitel und Satzgrenzen werden gelesen",
    "zh": "正在读取字幕并识别句子边界"
  },
  "Creating an independent media clip": {
    "es": "Creando un clip independiente",
    "de": "Eigenständiger Medienclip wird erstellt",
    "zh": "正在创建独立的媒体片段"
  },
  "Generating reading translations and comprehension questions": {
    "es": "Generando traducciones de lectura y preguntas de comprensión",
    "de": "Leseübersetzungen und Verständnisfragen werden erstellt",
    "zh": "正在生成阅读译文和理解题"
  },
  "Packaging the offline learning page": {
    "es": "Preparando la página de aprendizaje sin conexión",
    "de": "Offline-Lernseite wird vorbereitet",
    "zh": "正在准备离线学习页面"
  },
  "Ready": {
    "es": "Lista",
    "de": "Bereit",
    "zh": "已就绪"
  },
  "Export failed": {
    "es": "Error de exportación",
    "de": "Export fehlgeschlagen",
    "zh": "导出失败"
  },
  "Stop and save the recording before changing sentences or playing audio.": {
    "es": "Detén y guarda la grabación antes de cambiar de frase o reproducir audio.",
    "de": "Stoppe und speichere die Aufnahme, bevor du den Satz wechselst oder Audio abspielst.",
    "zh": "请先停止并保存录音，再切换句子或播放音频。"
  },
  "{n} / {total} sentences": {
    "es": "{n} / {total} frases",
    "de": "{n} / {total} Sätze",
    "zh": "第 {n} / {total} 句"
  },
  "· {n}/{total} reviewed": {
    "es": "· {n}/{total} repasadas",
    "de": "· {n}/{total} wiederholt",
    "zh": "· 已复习 {n}/{total}"
  },
  "Sentence finished. Review, repeat, or continue.": {
    "es": "Frase terminada. Repasa, repite o continúa.",
    "de": "Satz beendet. Wiederhole oder fahre fort.",
    "zh": "本句播放结束，可以复习、重复或继续。"
  },
  "Tap the player to start audio on this device.": {
    "es": "Toca el reproductor para iniciar el audio en este dispositivo.",
    "de": "Tippe auf den Player, um Audio auf diesem Gerät zu starten.",
    "zh": "点击播放器开始在此设备上播放音频。"
  },
  "Clip finished. Choose a sentence to review.": {
    "es": "Clip terminado. Elige una frase para repasar.",
    "de": "Clip beendet. Wähle einen Satz zum Wiederholen.",
    "zh": "片段已播放完毕，请选择要复习的句子。"
  },
  "Sentence copied.": {
    "es": "Frase copiada.",
    "de": "Satz kopiert.",
    "zh": "句子已复制。"
  },
  "Sentence selected. Use Copy from the browser menu.": {
    "es": "Frase seleccionada. Usa Copiar en el menú del navegador.",
    "de": "Satz ausgewählt. Wähle Kopieren im Browsermenü.",
    "zh": "句子已选中，请使用浏览器菜单中的“复制”。"
  },
  "This sentence has no translation in the shared package. Ask the sender to include translations when exporting.": {
    "es": "Esta frase no tiene traducción en la lección compartida. Pide al remitente que incluya traducciones al exportar.",
    "de": "Für diesen Satz ist keine Übersetzung in der geteilten Lektion enthalten. Bitte den Absender, beim Export Übersetzungen einzuschließen.",
    "zh": "分享的课程中没有此句的译文，请让发送者在导出时包含翻译。"
  },
  "No saved translation for this sentence. Translate while connected to keep it offline.": {
    "es": "No hay traducción guardada de esta frase. Tradúcela con conexión para conservarla sin conexión.",
    "de": "Keine gespeicherte Übersetzung für diesen Satz. Übersetze ihn bei bestehender Verbindung, um ihn offline zu behalten.",
    "zh": "本句暂无已保存的译文。联网翻译后即可离线查看。"
  },
  "Translating…": {
    "es": "Traduciendo…",
    "de": "Wird übersetzt…",
    "zh": "正在翻译…"
  },
  "Translation unavailable": {
    "es": "Traducción no disponible",
    "de": "Übersetzung nicht verfügbar",
    "zh": "翻译暂不可用"
  },
  "Translation timed out. Try again.": {
    "es": "La traducción tardó demasiado. Inténtalo de nuevo.",
    "de": "Zeitüberschreitung bei der Übersetzung. Versuche es erneut.",
    "zh": "翻译超时，请重试。"
  },
  "Attempt {n} · {time}": {
    "es": "Intento {n} · {time}",
    "de": "Versuch {n} · {time}",
    "zh": "第 {n} 次 · {time}"
  },
  "Could not delete this recording from browser storage.": {
    "es": "No se pudo eliminar esta grabación del navegador.",
    "de": "Die Aufnahme konnte nicht aus dem Browserspeicher gelöscht werden.",
    "zh": "无法从浏览器存储中删除此录音。"
  },
  "Recording deleted.": {
    "es": "Grabación eliminada.",
    "de": "Aufnahme gelöscht.",
    "zh": "录音已删除。"
  },
  "Recording needs a trusted HTTPS page and microphone support. Open the hosted page, then save it offline.": {
    "es": "La grabación requiere una página HTTPS de confianza y acceso al micrófono. Abre la página alojada y guárdala sin conexión.",
    "de": "Aufnahmen benötigen eine vertrauenswürdige HTTPS-Seite und Mikrofonunterstützung. Öffne die gehostete Seite und speichere sie offline.",
    "zh": "录音需要受信任的 HTTPS 页面和麦克风支持。请打开在线页面，再保存供离线使用。"
  },
  "Recording failed. Your previous attempts are still saved.": {
    "es": "Error de grabación. Tus intentos anteriores siguen guardados.",
    "de": "Aufnahme fehlgeschlagen. Deine bisherigen Versuche bleiben gespeichert.",
    "zh": "录音失败，之前的录音仍然保留。"
  },
  "Recording saved on this device. Compare it with the original.": {
    "es": "Grabación guardada en este dispositivo. Compárala con el original.",
    "de": "Aufnahme auf diesem Gerät gespeichert. Vergleiche sie mit dem Original.",
    "zh": "录音已保存在此设备，可与原音进行对比。"
  },
  "Recording is ready, but browser storage is unavailable. Download it now to keep it.": {
    "es": "La grabación está lista, pero el almacenamiento del navegador no está disponible. Descárgala ahora para conservarla.",
    "de": "Die Aufnahme ist fertig, aber der Browserspeicher ist nicht verfügbar. Lade sie jetzt herunter, um sie zu behalten.",
    "zh": "录音已完成，但浏览器存储不可用。请立即下载以保留录音。"
  },
  "No audio was captured. Check microphone access and try again.": {
    "es": "No se capturó audio. Comprueba el acceso al micrófono e inténtalo de nuevo.",
    "de": "Kein Audio aufgenommen. Prüfe den Mikrofonzugriff und versuche es erneut.",
    "zh": "未录到声音，请检查麦克风权限后重试。"
  },
  "Recording… {time}": {
    "es": "Grabando… {time}",
    "de": "Aufnahme… {time}",
    "zh": "正在录音… {time}"
  },
  "Microphone access was not allowed. Enable it for this page and try again.": {
    "es": "No se permitió el acceso al micrófono. Actívalo para esta página e inténtalo de nuevo.",
    "de": "Mikrofonzugriff wurde nicht erlaubt. Aktiviere ihn für diese Seite und versuche es erneut.",
    "zh": "未获准使用麦克风。请为此页面开启麦克风权限后重试。"
  },
  "Could not start recording: {error}": {
    "es": "No se pudo iniciar la grabación: {error}",
    "de": "Aufnahme konnte nicht gestartet werden: {error}",
    "zh": "无法开始录音：{error}"
  },
  "Tap Play on your recording to hear it.": {
    "es": "Pulsa Reproducir en tu grabación para escucharla.",
    "de": "Tippe bei deiner Aufnahme auf Abspielen, um sie zu hören.",
    "zh": "点击录音的播放按钮进行试听。"
  },
  "Listen · {time}": {
    "es": "Escuchar · {time}",
    "de": "Anhören · {time}",
    "zh": "听一句 · {time}"
  },
  "Long subtitle passages without sentence punctuation are divided into short review sections. Timing follows subtitle word timestamps where available.": {
    "es": "Los pasajes largos sin puntuación se dividen en secciones cortas para repasar. Se usan las marcas de tiempo de las palabras cuando están disponibles.",
    "de": "Lange Untertitel ohne Satzzeichen werden in kurze Abschnitte aufgeteilt. Wenn vorhanden, werden Wortzeitstempel verwendet.",
    "zh": "没有句末标点的长字幕会分成较短的复习片段。有逐词时间戳时，会优先使用逐词时间。"
  },
  "Answer in your own words, then compare with the suggested answer.": {
    "es": "Responde con tus propias palabras y compara con la respuesta sugerida.",
    "de": "Antworte mit eigenen Worten und vergleiche dann mit dem Antwortvorschlag.",
    "zh": "请用自己的话作答，再对照参考答案。"
  },
  "This package includes the original reading and vocabulary exercises. Select the optional local-LLM exercises when exporting to include comprehension questions and a reading translation.": {
    "es": "Esta lección incluye la lectura original y ejercicios de vocabulario. Selecciona los ejercicios opcionales del modelo local al exportar para incluir preguntas de comprensión y una traducción.",
    "de": "Diese Lektion enthält den Originaltext und Wortschatzübungen. Wähle beim Export die optionalen Modellübungen, um Verständnisfragen und eine Übersetzung einzuschließen.",
    "zh": "本课程包含原文阅读和词汇练习。导出时可勾选本地模型练习，以加入理解题和阅读译文。"
  },
  "Your answer to question {n}": {
    "es": "Tu respuesta a la pregunta {n}",
    "de": "Deine Antwort auf Frage {n}",
    "zh": "第 {n} 题的回答"
  },
  "Show suggested answer": {
    "es": "Mostrar respuesta sugerida",
    "de": "Antwortvorschlag anzeigen",
    "zh": "显示参考答案"
  },
  "Missing word {n}": {
    "es": "Palabra que falta {n}",
    "de": "Fehlendes Wort {n}",
    "zh": "第 {n} 个空缺单词"
  },
  "Check word": {
    "es": "Comprobar palabra",
    "de": "Wort prüfen",
    "zh": "检查单词"
  },
  "Correct.": {
    "es": "Correcto.",
    "de": "Richtig.",
    "zh": "正确。"
  },
  "Saved subtitle word: {word}": {
    "es": "Palabra del subtítulo: {word}",
    "de": "Wort im Untertitel: {word}",
    "zh": "字幕中的单词：{word}"
  },
  "No saved reading translation for this language. Translate sentences while connected, or export with optional LLM exercises.": {
    "es": "No hay traducción de lectura guardada en este idioma. Traduce las frases con conexión o exporta con los ejercicios opcionales del modelo.",
    "de": "Keine gespeicherte Leseübersetzung in dieser Sprache. Übersetze Sätze bei Verbindung oder exportiere mit den optionalen Modellübungen.",
    "zh": "此语言暂无已保存的阅读译文。请联网翻译句子，或在导出时勾选模型练习。"
  },
  "[Sentence {n}: translation not saved]": {
    "es": "[Frase {n}: traducción no guardada]",
    "de": "[Satz {n}: Übersetzung nicht gespeichert]",
    "zh": "[第 {n} 句：译文未保存]"
  },
  "No saved dictionary entries match this language or search.": {
    "es": "No hay entradas guardadas que coincidan con este idioma o búsqueda.",
    "de": "Keine gespeicherten Wörterbucheinträge für diese Sprache oder Suche.",
    "zh": "没有符合此语言或搜索条件的离线词条。"
  },
  "{correct} correct · {wrong} to practise again · progress saved on this device": {
    "es": "{correct} correctas · {wrong} para repasar · progreso guardado en este dispositivo",
    "de": "{correct} richtig · {wrong} erneut üben · Fortschritt auf diesem Gerät gespeichert",
    "zh": "答对 {correct} 次 · 待练习 {wrong} 次 · 进度保存在此设备"
  },
  "Not enough distinct vocabulary for this language yet.": {
    "es": "Aún no hay suficientes palabras distintas para este idioma.",
    "de": "Noch nicht genügend unterschiedliche Wörter für diese Sprache.",
    "zh": "此语言可用的不同词汇还不够。"
  },
  "These words share the same meaning. Try another language or review the vocabulary table.": {
    "es": "Estas palabras comparten el mismo significado. Prueba otro idioma o repasa la tabla de vocabulario.",
    "de": "Diese Wörter haben dieselbe Bedeutung. Probiere eine andere Sprache oder wiederhole die Wortschatztabelle.",
    "zh": "这些单词的词义相同，请尝试其他语言，或复习词汇表。"
  },
  "Correct": {
    "es": "Correcto",
    "de": "Richtig",
    "zh": "正确"
  },
  "Answer: {answer}": {
    "es": "Respuesta: {answer}",
    "de": "Antwort: {answer}",
    "zh": "答案：{answer}"
  },
  "{result} · {seconds} seconds. {next}": {
    "es": "{result} · {seconds} segundos. {next}",
    "de": "{result} · {seconds} Sekunden. {next}",
    "zh": "{result} · 用时 {seconds} 秒。{next}"
  },
  "Choose Random question to continue.": {
    "es": "Elige Pregunta aleatoria para continuar.",
    "de": "Wähle Zufällige Frage, um fortzufahren.",
    "zh": "点击“随机出题”继续。"
  },
  "This word will appear more often.": {
    "es": "Esta palabra aparecerá más a menudo.",
    "de": "Dieses Wort erscheint künftig häufiger.",
    "zh": "此单词以后会更频繁地出现。"
  },
  "Saved offline on this device: player, media, reading and vocabulary. Recordings stay in browser storage.": {
    "es": "Guardado sin conexión en este dispositivo: reproductor, medios, lectura y vocabulario. Las grabaciones quedan en el navegador.",
    "de": "Offline auf diesem Gerät gespeichert: Player, Medien, Lesetext und Wortschatz. Aufnahmen bleiben im Browserspeicher.",
    "zh": "已在此设备离线保存播放器、媒体、阅读和词汇。录音保存在浏览器存储中。"
  },
  "{n}/{total} files saved. Choose Save offline to complete this clip.": {
    "es": "{n}/{total} archivos guardados. Pulsa Guardar sin conexión para completar el clip.",
    "de": "{n}/{total} Dateien gespeichert. Wähle Offline speichern, um den Clip zu vervollständigen.",
    "zh": "已保存 {n}/{total} 个文件。请点击“保存供离线使用”以完成保存。"
  },
  "Open the hosted HTTPS learning page to save it offline.": {
    "es": "Abre la página de aprendizaje alojada con HTTPS para guardarla sin conexión.",
    "de": "Öffne die gehostete HTTPS-Lernseite, um sie offline zu speichern.",
    "zh": "请打开在线的 HTTPS 学习页面，再保存供离线使用。"
  },
  "The offline player is not ready yet. Try again.": {
    "es": "El reproductor sin conexión aún no está listo. Inténtalo de nuevo.",
    "de": "Der Offline-Player ist noch nicht bereit. Versuche es erneut.",
    "zh": "离线播放器尚未准备好，请重试。"
  },
  "The package file list is unavailable.": {
    "es": "La lista de archivos de la lección no está disponible.",
    "de": "Die Dateiliste der Lektion ist nicht verfügbar.",
    "zh": "无法获取课程文件列表。"
  },
  "Saving offline {n}/{total}: {file}…": {
    "es": "Guardando sin conexión {n}/{total}: {file}…",
    "de": "Offline speichern {n}/{total}: {file}…",
    "zh": "正在离线保存 {n}/{total}：{file}…"
  },
  "Could not save {file}": {
    "es": "No se pudo guardar {file}",
    "de": "{file} konnte nicht gespeichert werden",
    "zh": "无法保存 {file}"
  },
  "Offline save incomplete. {error}": {
    "es": "Guardado sin conexión incompleto. {error}",
    "de": "Offline-Speicherung unvollständig. {error}",
    "zh": "离线保存未完成。{error}"
  },
  "Offline copy removed. Voice recordings and study progress have been kept.": {
    "es": "Copia sin conexión eliminada. Se han conservado las grabaciones y el progreso.",
    "de": "Offline-Kopie entfernt. Aufnahmen und Lernfortschritt bleiben erhalten.",
    "zh": "离线副本已删除，录音和学习进度仍然保留。"
  },
  "{n} sentences · {duration} clip · original {start}–{end}": {
    "es": "{n} frases · clip de {duration} · original {start}–{end}",
    "de": "{n} Sätze · Clip {duration} · Original {start}–{end}",
    "zh": "{n} 句 · 片段时长 {duration} · 原视频 {start}–{end}"
  },
  "Shared learning clip · Link expires {date}. Save offline before expiry. Your voice and progress stay on this device.": {
    "es": "Clip de aprendizaje compartido · El enlace caduca el {date}. Guárdalo sin conexión antes de que caduque. Tu voz y progreso quedan en este dispositivo.",
    "de": "Geteilter Lernclip · Link gültig bis {date}. Vor Ablauf offline speichern. Deine Stimme und dein Fortschritt bleiben auf diesem Gerät.",
    "zh": "分享的学习片段 · 链接将于 {date} 到期。请在到期前离线保存，录音和进度保存在此设备。"
  },
  "Dictionary entries are included in this lesson. Your practice stays on this device.": {
    "es": "Las entradas del diccionario se incluyen en esta lección. Tu práctica queda en este dispositivo.",
    "de": "Wörterbucheinträge sind in dieser Lektion enthalten. Deine Übungen bleiben auf diesem Gerät.",
    "zh": "课程已包含词典条目，练习记录保存在此设备。"
  },
  "Browser storage is unavailable. You can still record and download attempts, but progress may not survive closing this page.": {
    "es": "El almacenamiento del navegador no está disponible. Puedes grabar y descargar intentos, pero el progreso puede perderse al cerrar la página.",
    "de": "Der Browserspeicher ist nicht verfügbar. Du kannst aufnehmen und Versuche herunterladen, aber beim Schließen kann der Fortschritt verloren gehen.",
    "zh": "浏览器存储不可用。仍可录音并下载，但关闭页面后可能丢失学习进度。"
  },
  "Could not open this learning clip: {error}": {
    "es": "No se pudo abrir este clip de aprendizaje: {error}",
    "de": "Dieser Lernclip konnte nicht geöffnet werden: {error}",
    "zh": "无法打开此学习片段：{error}"
  },
  "Not in this shared clip’s dictionary.": {
    "es": "No está en el diccionario de este clip compartido.",
    "de": "Nicht im Wörterbuch dieses geteilten Clips enthalten.",
    "zh": "此分享片段的词典中没有该词。"
  },
  "Not in this clip’s offline dictionary. Connect to look up this word.": {
    "es": "No está en el diccionario sin conexión de este clip. Conéctate para consultar la palabra.",
    "de": "Nicht im Offline-Wörterbuch dieses Clips enthalten. Verbinde dich, um das Wort nachzuschlagen.",
    "zh": "此片段的离线词典中没有该词，请联网查询。"
  },
  "Also: {meanings}": {
    "es": "También: {meanings}",
    "de": "Auch: {meanings}",
    "zh": "其他词义：{meanings}"
  },
  "{n} sentences · {minutes} minutes": {
    "es": "{n} frases · {minutes} minutos",
    "de": "{n} Sätze · {minutes} Minuten",
    "zh": "{n} 句 · {minutes} 分钟"
  },
  "Share this lesson": {
    "es": "Compartir esta lección",
    "de": "Diese Lektion teilen",
    "zh": "分享此课程"
  },
  "Browser storage unavailable": {
    "es": "Almacenamiento del navegador no disponible",
    "de": "Browserspeicher nicht verfügbar",
    "zh": "浏览器存储不可用"
  },
  "Flashcards will sync when connected": {
    "es": "Las tarjetas se sincronizarán al conectar",
    "de": "Lernkarten werden bei Verbindung synchronisiert",
    "zh": "联网后会同步闪卡"
  },
  "Could not start the learning export. Try again.": {
    "es": "No se pudo iniciar la exportación de aprendizaje. Inténtalo de nuevo.",
    "de": "Der Lernexport konnte nicht gestartet werden. Versuche es erneut.",
    "zh": "无法开始导出学习课程，请重试。"
  },
  "Could not start sharing. Try again.": {
    "es": "No se pudo empezar a compartir. Inténtalo de nuevo.",
    "de": "Die Freigabe konnte nicht gestartet werden. Versuche es erneut.",
    "zh": "无法开始分享，请重试。"
  },
  "Could not publish the lesson on Frankfurt. Please try again.": {
    "es": "No se pudo publicar la lección en Frankfurt. Inténtalo de nuevo.",
    "de": "Die Lektion konnte nicht auf Frankfurt veröffentlicht werden. Versuche es erneut.",
    "zh": "无法将课程发布到法兰克福，请重试。"
  },
  "Could not revoke the link on Frankfurt. Please try again.": {
    "es": "No se pudo revocar el enlace en Frankfurt. Inténtalo de nuevo.",
    "de": "Der Link auf Frankfurt konnte nicht widerrufen werden. Versuche es erneut.",
    "zh": "无法撤销法兰克福的链接，请重试。"
  },
  "Another share is being uploaded. Please wait.": {
    "es": "Se está subiendo otra lección. Espera, por favor.",
    "de": "Eine andere Freigabe wird hochgeladen. Bitte warte.",
    "zh": "另一个分享正在上传，请稍候。"
  },
  "Choose a 1-day or 5-day link.": {
    "es": "Elige un enlace de 1 o 5 días.",
    "de": "Wähle einen Link für 1 oder 5 Tage.",
    "zh": "请选择有效期为 1 天或 5 天的链接。"
  },
  "Export the learning clip first.": {
    "es": "Exporta primero el clip de aprendizaje.",
    "de": "Exportiere zuerst den Lernclip.",
    "zh": "请先导出学习片段。"
  },
  "Choose an exported learning clip.": {
    "es": "Elige un clip de aprendizaje exportado.",
    "de": "Wähle einen exportierten Lernclip.",
    "zh": "请选择已导出的学习片段。"
  },
  "The local translator is busy. Export again later to add exercises.": {
    "es": "El traductor local está ocupado. Exporta de nuevo más tarde para añadir ejercicios.",
    "de": "Der lokale Übersetzer ist beschäftigt. Exportiere später erneut, um Übungen hinzuzufügen.",
    "zh": "本地翻译器正忙，请稍后重新导出以添加练习。"
  },
  "The local LLM could not generate exercises. Export again later to retry.": {
    "es": "El modelo local no pudo generar los ejercicios. Exporta de nuevo más tarde para reintentarlo.",
    "de": "Das lokale Sprachmodell konnte keine Übungen erstellen. Exportiere später erneut.",
    "zh": "本地大模型未能生成练习，请稍后重新导出重试。"
  },
  "The model returned no usable comprehension questions.": {
    "es": "El modelo no devolvió preguntas de comprensión válidas.",
    "de": "Das Modell lieferte keine brauchbaren Verständnisfragen.",
    "zh": "模型未返回可用的理解题。"
  },
  "Reading translations were saved, but the model returned no usable comprehension questions. Export again later to retry.": {
    "es": "Las traducciones se guardaron, pero el modelo no devolvió preguntas válidas. Exporta de nuevo más tarde para reintentarlo.",
    "de": "Die Übersetzungen wurden gespeichert, aber das Modell lieferte keine brauchbaren Fragen. Exportiere später erneut.",
    "zh": "阅读译文已保存，但模型未返回可用的理解题。请稍后重新导出重试。"
  },
  "Invalid generated question.": {
    "es": "Pregunta generada no válida.",
    "de": "Ungültige generierte Frage.",
    "zh": "生成的题目格式无效。"
  },
  "Translator is busy. Please try again shortly.": {
    "es": "El traductor está ocupado. Inténtalo de nuevo en breve.",
    "de": "Der Übersetzer ist beschäftigt. Versuche es gleich noch einmal.",
    "zh": "翻译器正忙，请稍后重试。"
  },
  "verb": {
    "es": "verbo",
    "de": "Verb",
    "zh": "动词"
  },
  "noun": {
    "es": "sustantivo",
    "de": "Substantiv",
    "zh": "名词"
  },
  "adjective": {
    "es": "adjetivo",
    "de": "Adjektiv",
    "zh": "形容词"
  },
  "adverb": {
    "es": "adverbio",
    "de": "Adverb",
    "zh": "副词"
  },
  "pronoun": {
    "es": "pronombre",
    "de": "Pronomen",
    "zh": "代词"
  },
  "preposition": {
    "es": "preposición",
    "de": "Präposition",
    "zh": "介词"
  },
  "conjunction": {
    "es": "conjunción",
    "de": "Konjunktion",
    "zh": "连词"
  },
  "interjection": {
    "es": "interjección",
    "de": "Interjektion",
    "zh": "感叹词"
  },
  "article": {
    "es": "artículo",
    "de": "Artikel",
    "zh": "冠词"
  },
  "phrase": {
    "es": "expresión",
    "de": "Wendung",
    "zh": "短语"
  },
  "No learning clips yet.": {
    "es": "Aún no hay clips de aprendizaje.",
    "de": "Noch keine Lernclips.",
    "zh": "暂无学习片段。"
  },
  "Other languages": {
    "es": "Otros idiomas",
    "de": "Weitere Sprachen",
    "zh": "其他语言"
  },
  "Learning clip languages": {
    "es": "Idiomas de los clips de aprendizaje",
    "de": "Sprachen der Lernclips",
    "zh": "学习片段语言"
  }
};
  let language;
  try { language = localStorage.getItem('ytwatcher:lesson-ui-language'); } catch (error) {}
  if (!['en', 'es', 'de', 'zh'].includes(language)) language = (navigator.language || 'en').split('-')[0];
  if (!['en', 'es', 'de', 'zh'].includes(language)) language = 'en';
  const bindings = new Map(), attributes = new Map(), native = {en: 'English', es: 'Español', de: 'Deutsch', zh: '中文'};
  function t(key, values = {}) {
    if (typeof values === 'function') values = values();
    const template = language === 'en' ? key : (messages[key]?.[language] || key);
    return template.replace(/\{(\w+)\}/g, (match, name) => values[name] === undefined ? match : String(values[name]));
  }
  function text(element, key, values = {}) {
    if (!element) return;
    bindings.set(element, {key, values});
    element.textContent = t(key, values);
  }
  function raw(element, value) {
    text(element, '{raw}', () => ({raw: typeof value === 'function' ? value() : value}));
  }
  function attribute(element, name, key, values = {}) {
    if (!attributes.has(element)) attributes.set(element, new Map());
    attributes.get(element).set(name, {key, values});
    element.setAttribute(name, t(key, values));
  }
  function forget(element) { bindings.delete(element); }
  function apply(root = document) {
    root.querySelectorAll('[data-i18n]').forEach(element => { element.textContent = t(element.dataset.i18n, JSON.parse(element.dataset.i18nValues || '{}')); });
    for (const name of ['aria-label', 'placeholder', 'title']) {
      root.querySelectorAll('[data-i18n-' + name + ']').forEach(element => element.setAttribute(name, t(element.getAttribute('data-i18n-' + name))));
    }
    for (const [element, value] of bindings) {
      if (!element.isConnected) { bindings.delete(element); continue; }
      element.textContent = t(value.key, value.values);
    }
    for (const [element, values] of attributes) {
      if (!element.isConnected) { attributes.delete(element); continue; }
      for (const [name, value] of values) element.setAttribute(name, t(value.key, value.values));
    }
    root.querySelectorAll('[data-ui-language]').forEach(select => {
      if (!select.options.length) for (const [code, label] of Object.entries(native)) select.append(new Option(label, code));
      select.value = language;
      select.onchange = () => setLanguage(select.value);
    });
  }
  function setLanguage(value) {
    if (!Object.hasOwn(native, value)) return;
    language = value;
    try { localStorage.setItem('ytwatcher:lesson-ui-language', value); } catch (error) {}
    if (document.body?.dataset.learningPage === 'true') document.documentElement.lang = value;
    apply();
    window.dispatchEvent(new CustomEvent('yt-lesson-language', {detail: value}));
  }
  window.YtLessonI18n = {t, text, raw, attribute, forget, apply, setLanguage, get language() { return language; }};
  function ready() {
    if (document.body?.dataset.learningPage === 'true') document.documentElement.lang = language;
    apply();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready, {once: true}); else ready();
})();
