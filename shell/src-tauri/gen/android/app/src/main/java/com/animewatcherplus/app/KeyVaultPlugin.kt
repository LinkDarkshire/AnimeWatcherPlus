package com.animewatcherplus.app

import android.app.Activity
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

@InvokeArg
class VaultArgs {
  lateinit var data: String
}

/** Seals the device key (src-tauri/src/keyvault.rs) with an AES key kept in
 * the Android Keystore -- in StrongBox where the phone has one. That key
 * never leaves the secure hardware, so the sealed file in the app's storage
 * is useless anywhere but on this phone. */
@TauriPlugin
class KeyVaultPlugin(private val activity: Activity) : Plugin(activity) {
  private val alias = "animewatcherplus-device-key-seal"

  private fun secretKey(): SecretKey {
    val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    (store.getKey(alias, null) as? SecretKey)?.let { return it }

    fun generate(strongBox: Boolean): SecretKey {
      val spec = KeyGenParameterSpec.Builder(
        alias,
        KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
      )
        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
        .setKeySize(256)
        .apply { if (strongBox && Build.VERSION.SDK_INT >= 28) setIsStrongBoxBacked(true) }
        .build()
      val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
      generator.init(spec)
      return generator.generateKey()
    }
    return try {
      generate(strongBox = true)
    } catch (e: Exception) {
      // No StrongBox on this phone: the regular (TEE-backed) keystore.
      generate(strongBox = false)
    }
  }

  @Command
  fun seal(invoke: Invoke) {
    try {
      val args = invoke.parseArgs(VaultArgs::class.java)
      val cipher = Cipher.getInstance("AES/GCM/NoPadding")
      cipher.init(Cipher.ENCRYPT_MODE, secretKey())
      val sealed = cipher.iv + cipher.doFinal(Base64.decode(args.data, Base64.NO_WRAP))
      invoke.resolve(JSObject().put("data", Base64.encodeToString(sealed, Base64.NO_WRAP)))
    } catch (e: Exception) {
      invoke.reject("seal failed: ${e.message}")
    }
  }

  @Command
  fun open(invoke: Invoke) {
    try {
      val args = invoke.parseArgs(VaultArgs::class.java)
      val sealed = Base64.decode(args.data, Base64.NO_WRAP)
      val cipher = Cipher.getInstance("AES/GCM/NoPadding")
      cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(128, sealed.copyOfRange(0, 12)))
      val data = cipher.doFinal(sealed.copyOfRange(12, sealed.size))
      invoke.resolve(JSObject().put("data", Base64.encodeToString(data, Base64.NO_WRAP)))
    } catch (e: Exception) {
      invoke.reject("open failed: ${e.message}")
    }
  }
}
