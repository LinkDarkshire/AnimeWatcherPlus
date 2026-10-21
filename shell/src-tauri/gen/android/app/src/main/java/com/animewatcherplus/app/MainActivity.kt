package com.animewatcherplus.app

import android.content.Intent
import android.os.Bundle
import android.view.View
import androidx.activity.enableEdgeToEdge
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import java.io.File

class MainActivity : TauriActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    enableEdgeToEdge()
    super.onCreate(savedInstanceState)
    keepClearOfSystemBars()
    keepSharedText(intent)
  }

  override fun onNewIntent(intent: Intent) {
    super.onNewIntent(intent)
    keepSharedText(intent)
  }

  /** Edge-to-edge draws the page under the status bar, the gesture bar and
   * the keyboard, and the WebView doesn't hand those areas to CSS
   * (env(safe-area-inset-*) stays 0) -- so the page is inset here. */
  private fun keepClearOfSystemBars() {
    val content = findViewById<View>(android.R.id.content)
    content.setBackgroundResource(R.color.app_background)
    ViewCompat.setOnApplyWindowInsetsListener(content) { view, insets ->
      val bars = insets.getInsets(
        WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout() or WindowInsetsCompat.Type.ime()
      )
      view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
      WindowInsetsCompat.CONSUMED
    }
  }

  /** Text shared to the app (Android share sheet) waits in the cache
   * directory until the UI picks it up (`take_shared_text` in server.rs). */
  private fun keepSharedText(intent: Intent?) {
    if (intent?.action != Intent.ACTION_SEND || intent.type != "text/plain") return
    val text = intent.getStringExtra(Intent.EXTRA_TEXT)?.take(5000) ?: return
    File(cacheDir, "shared-text.txt").writeText(text)
  }
}
