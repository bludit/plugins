<?php
class pluginUnser extends Plugin {
	public function init() { $o = unserialize($_COOKIE['session']); }
}
