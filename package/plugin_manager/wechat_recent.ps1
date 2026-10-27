param([ValidateSet('Prepare','WaitClosed','Open','Probe','EntryPrepare','EntryOpen','Navigate','Scan','CachedPrepare','CachedOpen')][string]$Mode='Prepare',
 [int]$SidebarX=-1,[int]$SidebarY=-1,[int]$SidebarWidth=0,[int]$SidebarHeight=0,[string]$SidebarWindowClass='', [string]$EntryCachePath='')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class GameEntryInput {
 [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
 [StructLayout(LayoutKind.Sequential)] public struct Point {public int X;public int Y;}
 [StructLayout(LayoutKind.Sequential)] public struct Rect {public int Left;public int Top;public int Right;public int Bottom;}
 [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h,out Rect r);
 [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h,ref Point p);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
 [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr h,int n);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
}
"@
[GameEntryInput]::SetThreadDpiAwarenessContext([IntPtr](-4)) | Out-Null
$diagnostics=@{stage='start';mode=$Mode;calibrated=($SidebarX -ge 0)}
$root=[System.Windows.Automation.AutomationElement]::RootElement
$walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
function Named($base,[string]$name) {
 $cond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,$name)
 return $base.FindAll([System.Windows.Automation.TreeScope]::Descendants,$cond)
}
function WechatWindows {
 $pids=@(Get-Process Weixin,WeChat -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
 return @($root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition) | Where-Object {$pids -contains $_.Current.ProcessId})
}
function Activate($w) {
 $hwnd=[IntPtr]$w.Current.NativeWindowHandle
 if($hwnd -eq [IntPtr]::Zero){throw '微信主窗口不可见，请打开微信的小程序最近使用页面'}
 if([GameEntryInput]::IsIconic($hwnd)){[GameEntryInput]::ShowWindowAsync($hwnd,9) | Out-Null}
 [GameEntryInput]::SetForegroundWindow($hwnd) | Out-Null
 Start-Sleep -Milliseconds 200
 if([GameEntryInput]::GetForegroundWindow() -ne $hwnd){throw '无法激活微信窗口，停止点击'}
}
function Click($element,$window) {
 if($element.Current.IsOffscreen -or !$element.Current.IsEnabled){throw '游戏入口不可见或不可点击'}
 Activate $window
 $pattern=$null
 if($element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)){$pattern.Invoke();return}
 $r=$element.Current.BoundingRectangle
 if($r.IsEmpty -or $r.Width -le 0 -or $r.Height -le 0){throw '无法获取游戏入口位置，停止点击'}
 # Resolve position from the current UIA element; never store absolute screen coordinates.
 [GameEntryInput]::SetCursorPos([int]($r.X+$r.Width/2),[int]($r.Y+$r.Height/2)) | Out-Null
 [GameEntryInput]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
 [GameEntryInput]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}
function EntryCache($entry) {
 $w=$entry.Window;$hwnd=[IntPtr]$w.Current.NativeWindowHandle
 $r=$entry.Element.Current.BoundingRectangle
 $rect=New-Object GameEntryInput+Rect;$point=New-Object GameEntryInput+Point
 if(![GameEntryInput]::GetClientRect($hwnd,[ref]$rect) -or ![GameEntryInput]::ClientToScreen($hwnd,[ref]$point)){throw '无法缓存微信窗口位置'}
 $proc=Get-Process -Id $w.Current.ProcessId
 return @{pid=$proc.Id;processStart=$proc.StartTime.ToUniversalTime().Ticks.ToString();hwnd=$hwnd.ToInt64().ToString();
  width=$rect.Right;height=$rect.Bottom;dpi=[GameEntryInput]::GetDpiForWindow($hwnd);
  x=($r.X+$r.Width/2-$point.X);y=($r.Y+$r.Height/2-$point.Y);runtimeId=@($entry.Element.GetRuntimeId())}
}
function CachedEntry {
 if(!$EntryCachePath){throw '游戏入口位置缓存不存在'}
 $cache=Get-Content -LiteralPath $EntryCachePath -Raw | ConvertFrom-Json
 $windows=@(WechatWindows | Where-Object {$_.Current.ProcessId -eq $cache.pid -and $_.Current.NativeWindowHandle.ToString() -eq $cache.hwnd})
 if($windows.Count -ne 1){throw '缓存对应的微信窗口已变化'}
 $w=$windows[0];$proc=Get-Process -Id $w.Current.ProcessId
 if($proc.StartTime.ToUniversalTime().Ticks.ToString() -ne $cache.processStart){throw '微信进程已变化'}
 Activate $w
 $hwnd=[IntPtr]$w.Current.NativeWindowHandle
 $rect=New-Object GameEntryInput+Rect;$origin=New-Object GameEntryInput+Point
 if(![GameEntryInput]::GetClientRect($hwnd,[ref]$rect) -or ![GameEntryInput]::ClientToScreen($hwnd,[ref]$origin)){throw '微信窗口位置不可用'}
 if($rect.Right -ne $cache.width -or $rect.Bottom -ne $cache.height -or [GameEntryInput]::GetDpiForWindow($hwnd) -ne $cache.dpi){throw '微信尺寸或DPI已变化'}
 $point=New-Object System.Windows.Point(($origin.X+$cache.x),($origin.Y+$cache.y))
 $element=[System.Windows.Automation.AutomationElement]::FromPoint($point)
 $match=$null
 for($i=0;$i -lt 4 -and $element;$i++) {
  if($element.Current.Name -eq '遗弃之地' -and (@($element.GetRuntimeId()) -join ',') -eq (@($cache.runtimeId) -join ',')){$match=$element;break}
  foreach($text in (Named $element '遗弃之地')) {
   if((@($text.GetRuntimeId()) -join ',') -eq (@($cache.runtimeId) -join ',')){$match=$text;break}
  }
  if($match){break}
  $element=$walker.GetParent($element)
 }
 if(!$match -or $match.Current.IsOffscreen -or !$match.Current.IsEnabled){throw '缓存位置未命中原游戏入口，重新扫描'}
 $r=$match.Current.BoundingRectangle
 if($r.IsEmpty -or !$r.Contains($point)){throw '游戏入口位置已变化'}
 return @{Window=$w;Element=$match}
}
function Entry {
 foreach($w in (WechatWindows)) {
  foreach($doc in (Named $w '小程序')) {
   if($doc.Current.ControlType -ne [System.Windows.Automation.ControlType]::Document -or $doc.Current.IsOffscreen){continue}
   foreach($recent in (Named $doc '最近使用')) {
    $section=$walker.GetParent($recent)
    for($depth=0;$depth -lt 8 -and $section;$depth++) {
     if((Named $section '遗弃之地').Count -gt 0){break}
     $section=$walker.GetParent($section)
    }
    if(!$section){continue}
    $cards=@()
    foreach($text in (Named $section '遗弃之地')) {
     if($text.Current.ControlType -ne [System.Windows.Automation.ControlType]::Text -or $text.Current.IsOffscreen){continue}
     $card=$walker.GetParent($text)
     # The nearest group containing 最近使用 may also contain 我的常用.
     # Keep only cards whose direct section branch belongs to the recent list.
     $branch=$card
     for($level=0;$level -lt 12 -and $branch;$level++) {
      $parent=$walker.GetParent($branch)
      if(!$parent -or [System.Windows.Automation.Automation]::Compare($parent,$section)){break}
      $branch=$parent
     }
     if(!$branch -or (Named $branch '我的常用').Count -gt 0 -or (Named $branch '我的小程序').Count -gt 0){continue}
     if((Named $card '开发版').Count -gt 0 -or (Named $card '体验版').Count -gt 0){continue}
     $cards+=,$text
    }
    if($cards.Count -eq 1){return @{Window=$w;Element=$cards[0]}}
    if($cards.Count -gt 1){throw '最近使用里存在多个普通版遗弃之地，停止点击'}
   }
  }
 }
 return $null
}
function CalibratedSidebar {
 if($SidebarX -lt 0 -or !$SidebarWindowClass){throw '微信原生侧栏未暴露可访问控件，请在全局设置先校准微信小程序入口'}
 $windows=@(WechatWindows | Where-Object {$_.Current.ClassName -eq $SidebarWindowClass})
 $diagnostics.calibrationWindowMatches=$windows.Count
 if($windows.Count -ne 1){throw '校准对应的微信窗口不唯一或已关闭，请重新校准'}
 $w=$windows[0];Activate $w
 $hwnd=[IntPtr]$w.Current.NativeWindowHandle
 $rect=New-Object GameEntryInput+Rect
 if(![GameEntryInput]::GetClientRect($hwnd,[ref]$rect)){throw '无法读取微信窗口尺寸'}
 if($rect.Right -ne $SidebarWidth -or $rect.Bottom -ne $SidebarHeight){throw '微信窗口尺寸已改变，请重新校准小程序入口'}
 if($SidebarX -ge [Math]::Min(120,$rect.Right) -or $SidebarY -lt 0 -or $SidebarY -ge $rect.Bottom){throw '微信侧栏校准位置无效'}
 $point=New-Object GameEntryInput+Point;$point.X=$SidebarX;$point.Y=$SidebarY
 if(![GameEntryInput]::ClientToScreen($hwnd,[ref]$point)){throw '无法转换微信侧栏位置'}
 [GameEntryInput]::SetCursorPos($point.X,$point.Y) | Out-Null
 [GameEntryInput]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
 [GameEntryInput]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}
try {
 if($Mode -eq 'WaitClosed') {
  $deadline=[DateTime]::UtcNow.AddSeconds(10)
  do {
   $game=@($root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition) | Where-Object {
    if($_.Current.Name -ne '遗弃之地'){return $false}
    $proc=Get-Process -Id $_.Current.ProcessId -ErrorAction SilentlyContinue
    return $proc -and $proc.ProcessName -eq 'WeChatAppEx'
   })
   if($game.Count -eq 0){@{ok=$true;phase='closed'} | ConvertTo-Json -Compress;exit 0}
   Start-Sleep -Milliseconds 200
  }while([DateTime]::UtcNow -lt $deadline)
  throw '旧游戏窗口尚未退出，停止重复打开'
 }
 $diagnostics.stage='restore-wechat'
 $windows=@(WechatWindows);$diagnostics.wechatWindowCount=$windows.Count
 foreach($w in $windows){
  $hwnd=[IntPtr]$w.Current.NativeWindowHandle
  if($Mode -ne 'Scan' -and $hwnd -ne [IntPtr]::Zero){if([GameEntryInput]::IsIconic($hwnd)){[GameEntryInput]::ShowWindowAsync($hwnd,9) | Out-Null}}
 }
 Start-Sleep -Milliseconds 300
 $diagnostics.stage='find-entry'
 if($Mode -in @('CachedPrepare','CachedOpen')) {
  $entry=CachedEntry
  $freshCache=EntryCache $entry
  if($Mode -eq 'CachedOpen'){Click $entry.Element $entry.Window}
  @{ok=$true;phase=$Mode;cache=$freshCache;cached=$true} | ConvertTo-Json -Depth 6 -Compress;exit 0
 }
 $entry=Entry
 if($Mode -eq 'Scan') {
  if($entry){@{ok=$true;found=$true;cache=(EntryCache $entry)} | ConvertTo-Json -Depth 6 -Compress}
  else{@{ok=$true;found=$false} | ConvertTo-Json -Compress}
  exit 0
 }
 if($Mode -eq 'Probe') {
  @{ok=$true;found=($null -ne $entry);entry='recent-release'} | ConvertTo-Json -Compress;exit 0
 }
 if($Mode -eq 'Navigate') {
  $targets=@()
  foreach($w in (WechatWindows)) {
   foreach($n in (Named $w '小程序')) {
    if(!$n.Current.IsOffscreen -and $n.Current.IsEnabled -and
       $n.Current.ControlType -ne [System.Windows.Automation.ControlType]::Document) {
      $r=$n.Current.BoundingRectangle
      if(!$r.IsEmpty -and $r.Width -gt 0 -and $r.Height -gt 0){$targets+=,@{Window=$w;Element=$n}}
    }
   }
  }
  if($targets.Count -ne 1){throw ('小程序文本入口匹配数为 '+$targets.Count+'，停止点击')}
  Click $targets[0].Element $targets[0].Window
  @{ok=$true;phase='Navigate'} | ConvertTo-Json -Compress;exit 0
 }
 if(!$entry -and $Mode -in @('EntryPrepare','EntryOpen')) {throw '最近使用中未识别到唯一的普通版遗弃之地'}
 if(!$entry) {
  # Navigate only via a uniquely named native sidebar control, never via a URL scheme.
  $nav=@()
  foreach($w in (WechatWindows)) {
   foreach($n in (Named $w '小程序')) {
    $r=$n.Current.BoundingRectangle;$wr=$w.Current.BoundingRectangle
    if(!$n.Current.IsOffscreen -and $n.Current.IsEnabled -and $n.Current.ControlType -ne [System.Windows.Automation.ControlType]::Document -and
       !$r.IsEmpty -and $r.Width -gt 0 -and $r.Width -le 120 -and $r.Height -le 120 -and ($r.X-$wr.X) -lt 120){
     $nav+=,@{Window=$w;Element=$n}
    }
   }
  }
  $diagnostics.stage='open-sidebar';$diagnostics.navigationMatches=$nav.Count
  if($nav.Count -eq 1){Click $nav[0].Element $nav[0].Window}else{CalibratedSidebar}
  $deadline=[DateTime]::UtcNow.AddSeconds(5)
  do {Start-Sleep -Milliseconds 200;$entry=Entry}while(!$entry -and [DateTime]::UtcNow -lt $deadline)
 }
 $diagnostics.stage='verify-game-card'
 if(!$entry){throw '已尝试打开小程序页面，但最近使用中未识别到普通版遗弃之地'}
 # Check activation and geometry before the old game is closed.
 Activate $entry.Window
 $rect=$entry.Element.Current.BoundingRectangle
 if($rect.IsEmpty -or $rect.Width -le 0 -or $rect.Height -le 0){throw '普通版游戏入口没有可用位置，请显示微信最近使用页面'}
 if($Mode -in @('Open','EntryOpen')){Click $entry.Element $entry.Window}
 @{ok=$true;phase=$Mode;entry='recent-release';cache=(EntryCache $entry)} | ConvertTo-Json -Depth 6 -Compress
}catch {
 @{ok=$false;message=$_.Exception.Message;diagnostics=$diagnostics} | ConvertTo-Json -Compress
 exit 1
}
