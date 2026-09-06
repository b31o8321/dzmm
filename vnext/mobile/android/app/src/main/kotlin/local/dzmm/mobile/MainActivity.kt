package local.dzmm.mobile

import com.chaquo.python.PyException
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import org.json.JSONObject
import java.util.concurrent.Executors

class MainActivity : FlutterActivity() {
    private val channelName = "dzmm/local_host"
    private val pythonWorker = Executors.newSingleThreadExecutor()
    private val backgroundOperations = setOf(
        "choose",
        "play_turn",
        "generate_ai_world_draft",
        "validate_ai_world_draft",
        "probe_model_profile",
    )
    private val supportedOperations = setOf(
        "runtime_health",
        "list_worlds",
        "get_world",
        "archive_world",
        "restore_world",
        "delete_world",
        "create_run",
        "list_model_profiles",
        "create_model_profile",
        "update_model_profile",
        "set_default_model_profile",
        "delete_model_profile",
        "probe_model_profile",
        "world_template",
        "compose_world",
        "get_run",
        "choose",
        "play_turn",
        "cancel_operation",
        "rollback",
        "generate_ai_world_draft",
        "validate_ai_world_draft",
        "export_world",
        "import_world",
        "export_run",
        "clone_run",
    )

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        val module = Python.getInstance().getModule("dzmm_local_host")
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
            .setMethodCallHandler { call, result ->
                try {
                    val arguments = (call.arguments as? Map<*, *>)?.toMutableMap()
                        ?: mutableMapOf<Any?, Any?>()
                    arguments["data_dir"] = filesDir.absolutePath
                    val argumentJson = encodeArguments(arguments)
                    if (call.method in backgroundOperations) {
                        pythonWorker.execute {
                            try {
                                val value = invoke(module, call.method, argumentJson)
                                runOnUiThread { result.success(value.toString()) }
                            } catch (error: PyException) {
                                runOnUiThread {
                                    result.error(
                                        "python_error",
                                        error.message ?: "embedded Python error",
                                        null,
                                    )
                                }
                            } catch (error: Exception) {
                                runOnUiThread {
                                    result.error(
                                        "bridge_error",
                                        error.message ?: "Local Host bridge error",
                                        null,
                                    )
                                }
                            }
                        }
                        return@setMethodCallHandler
                    }
                    val value = invoke(module, call.method, argumentJson)
                    result.success(value.toString())
                } catch (error: PyException) {
                    result.error("python_error", error.message ?: "embedded Python error", null)
                } catch (error: Exception) {
                    result.error("bridge_error", error.message ?: "Local Host bridge error", null)
                }
            }
    }

    private fun invoke(
        module: com.chaquo.python.PyObject,
        method: String,
        argumentJson: String,
    ): Any = if (method in supportedOperations) {
        module.callAttr(method, argumentJson)
    } else {
        module.callAttr(
            "unavailable",
            encodeArguments(mapOf("operation" to method)),
        )
    }

    override fun onDestroy() {
        pythonWorker.shutdownNow()
        super.onDestroy()
    }

    private fun encodeArguments(arguments: Map<*, *>): String {
        return JSONObject(arguments).toString()
    }
}
