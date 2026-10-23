using System;
using System.IO;
using System.Collections;
using System.Reflection;
using UnityEngine;
using UnityEngine.UI;
using inXile.UI;
using inXile.UI.TTON;

// Temporary integration test, using the previously verified menu/prefab hook.
public class TutorialLayoutProbe : MonoBehaviour {
    static bool started;
    public static void Begin(Component owner) {
        if (started) return;
        started = true;
        Application.runInBackground = true;
        GameObject runner = new GameObject("TemporaryLocalizationQA");
        UnityEngine.Object.DontDestroyOnLoad(runner);
        runner.AddComponent<TutorialLayoutProbe>();
    }
    IEnumerator Start() {
        string folder = @"D:\StaticHanHua\Projects\torment-tides-of-numenera\Analysis\input\tutorial_20261023";
        File.AppendAllText(Path.Combine(folder, "metrics.txt"), "begin runtime probe\n");
        yield return new WaitForSecondsRealtime(4);
        string[] titles = {"教程：努力", "教程：努力（手柄文本）", "物品栏", "剧情段落文字检查"};
        for (int i = 0; i < 4; i++) {
            TutorialMessageWindow window = inXile.UI.TTON.Windows.SpawnWindow<TutorialMessageWindow>();
            window.UnloadOnHide = true;
            window.SetMessage(titles[i], File.ReadAllText(Path.Combine(folder, "case" + i + ".txt")), "继续", "");
            window.Show();
            yield return new WaitForSecondsRealtime(1);
            Canvas.ForceUpdateCanvases();
            yield return null;
            Text label = (Text)typeof(MessageWindow).GetField("messageLabel", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(window);
            File.AppendAllText(Path.Combine(folder, "metrics.txt"), i + " used=" + label.cachedTextGenerator.fontSizeUsedForBestFit +
                " lines=" + label.cachedTextGenerator.lineCount + " font=" + label.fontSize +
                " bestFit=" + label.resizeTextForBestFit + " rect=" + label.rectTransform.rect +
                " text=" + label.text.Replace("\r", "\\r").Replace("\n", "\\n") + "\n");
            Application.CaptureScreenshot(Path.Combine(folder, "case" + i + ".png"));
            yield return new WaitForSecondsRealtime(1);
            window.gameObject.SetActive(false);
            UnityEngine.Object.Destroy(window.gameObject);
            yield return null;
        }
        File.WriteAllText(Path.Combine(folder, "done.txt"), "finished");
        Application.Quit();
    }
}
