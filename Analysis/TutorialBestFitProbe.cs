using System;
using System.IO;
using System.Collections;
using System.Reflection;
using UnityEngine;
using UnityEngine.UI;
using Candlelight.UI;
using inXile.UI.TTON;

// Temporary integration test only; never included in the final assembly payload.
public class TutorialBestFitProbe : MonoBehaviour {
    static bool started;
    const string Folder = @"D:\StaticHanHua\Projects\torment-tides-of-numenera\Analysis\input\tutorial_bestfit_20261023";
    public static void Begin() {
        if (started) return;
        started = true;
        File.AppendAllText(Path.Combine(Folder,"metrics.txt"), "Begin at GameState.Awake\n");
        Application.runInBackground = true;
        var obj = new GameObject("TemporaryBestFitQA");
        UnityEngine.Object.DontDestroyOnLoad(obj);
        obj.AddComponent<TutorialBestFitProbe>();
    }
    IEnumerator Start() {
        yield return new WaitForSecondsRealtime(12);
        for(int n=0; n<100 && !WindowList.HasInstance(); n++) yield return new WaitForSecondsRealtime(1);
        if (!WindowList.HasInstance()) {
            File.AppendAllText(Path.Combine(Folder,"metrics.txt"),"No WindowList available\n");
            Application.Quit(); yield break;
        }
        string[] cases = {"english", "chinese_baseline", "chinese_fixed", "skills_fixed"};
        for(int i=0;i<cases.Length;i++) {
            TutorialMessageWindow window = inXile.UI.TTON.Windows.SpawnWindow<TutorialMessageWindow>();
            string text=GUIUtils.Format(File.ReadAllText(Path.Combine(Folder,cases[i]+".txt")));
            window.SetMessage("物品栏",text,"继续","禁用教程");
            HyperText label=(HyperText)typeof(MessageWindow).GetField("messageLabel",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(window);
            // Restore original prefab behavior for the two control cases only.
            if(i<2) { label.resizeTextForBestFit=true; label.verticalOverflow=VerticalWrapMode.Truncate; }
            window.Show();
            yield return new WaitForSecondsRealtime(2);
            Canvas.ForceUpdateCanvases();
            yield return null;
            label.cachedTextGenerator.Populate(label.UploadedText,label.GetGenerationSettings(label.rectTransform.rect.size));
            File.AppendAllText(Path.Combine(Folder,"metrics.txt"),cases[i]+" bestFit="+label.resizeTextForBestFit+
                " effectiveFont="+(label.resizeTextForBestFit?label.cachedTextGenerator.fontSizeUsedForBestFit:label.FontSizeToUse)+
                " lines="+label.cachedTextGenerator.lineCount+" preferredHeight="+label.preferredHeight+
                " rect="+label.rectTransform.rect+" chars="+label.cachedTextGenerator.characterCount+
                " textChars="+text.Length+" screen="+Screen.width+"x"+Screen.height+"\n");
            Application.CaptureScreenshot(Path.Combine(Folder,cases[i]+".png"));
            yield return new WaitForSecondsRealtime(2);
            window.UnloadOnHide = true;
            window.Hide(false);
            yield return null;
        }
        File.WriteAllText(Path.Combine(Folder,"done.txt"),"finished");
        Application.Quit();
    }
}
