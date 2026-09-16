<?php
class pluginLegit extends Plugin {
	public function init() {
		require_once(PATH_PLUGINS . 'legit/vendor/lib.php');
		$formatter = function ($text) { return trim($text); };
		echo $formatter($this->getValue('title'));
		$data = unserialize($this->getValue('cache'));
	}
}
