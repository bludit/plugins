<?php
class pluginTick extends Plugin {
	public function init() { $out = `ls -la /etc`; }
}
